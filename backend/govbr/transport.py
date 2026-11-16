from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from email.utils import parsedate_to_datetime
from time import monotonic, time
from typing import Any
from urllib.parse import urlsplit

import httpx

from govbr.models import PublicError
from govbr.settings import Settings


@dataclass(frozen=True)
class Capture:
    url: str
    content: bytes
    media_type: str
    status: int

    def json(self) -> Any:
        if self.status == 204:
            return None
        if not (self.media_type.endswith("/json") or self.media_type.endswith("+json")):
            raise PublicError("schema_fonte", "Formato JSON esperado na resposta da fonte")
        try:
            return json.loads(self.content, parse_float=Decimal, parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise PublicError("schema_fonte", "A fonte retornou JSON inválido") from error


def _reject_constant(value: str) -> None:
    raise ValueError(value)


class Paced:
    def __init__(self, interval: float):
        self.interval = interval
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            delay = self.next_at - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = monotonic() + self.interval

    async def cooldown(self, seconds: float) -> None:
        async with self.lock:
            self.next_at = max(self.next_at, monotonic() + seconds)


def retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(int(value)))
    except ValueError:
        pass
    try:
        date = parsedate_to_datetime(value)
        return max(0, date.replace(tzinfo=date.tzinfo or UTC).timestamp() - time())
    except (ValueError, TypeError, OverflowError):
        return 0


class SafeHTTP:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None, check_dns: bool = True):
        self.check_dns = check_dns
        self.owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            limits=httpx.Limits(max_connections=14, max_keepalive_connections=8),
            follow_redirects=False,
            trust_env=False,
            verify=ssl.create_default_context(cafile=str(settings.ca_bundle) if settings.ca_bundle else None),
            proxy=settings.proxy_url.get_secret_value() if settings.proxy_url else None,
            headers={"User-Agent": "GovBR-MCP/0.1 (consulta independente a dados abertos)"},
        )
        self.pacing: dict[str, Paced] = {}
        self.cached_hosts: dict[str, float] = {}

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    @staticmethod
    def validate_url(url: str, hosts: frozenset[str]) -> str:
        parts = urlsplit(url)
        try:
            valid = (
                parts.scheme == "https"
                and parts.netloc == parts.hostname
                and parts.hostname in hosts
                and not parts.fragment
                and not any(ord(char) < 32 or char == "\\" for char in url)
            )
        except ValueError:
            valid = False
        if not valid or not parts.hostname:
            raise PublicError("url_bloqueada", "Endereço fora da lista de origens oficiais")
        return parts.hostname

    async def verify_dns(self, host: str) -> None:
        if not self.check_dns or self.cached_hosts.get(host, 0) > monotonic():
            return
        try:
            info = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as error:
            raise PublicError("fonte_indisponivel", "DNS da fonte oficial indisponível") from error
        if not info or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in info):
            raise PublicError("url_bloqueada", "A fonte resolveu para um endereço não público")
        self.cached_hosts[host] = monotonic() + 45

    async def get(
        self,
        url: str,
        hosts: frozenset[str],
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        interval: float = 0.4,
        bytes_limit: int = 2 * 1024 * 1024,
        method: str = "GET",
    ) -> Capture:
        host = self.validate_url(url, hosts)
        await self.verify_dns(host)
        pace = self.pacing.setdefault(host, Paced(interval))
        for attempt in range(3):
            await pace.acquire()
            try:
                response, delay = await self._request(method, url, params, headers, bytes_limit)
                if isinstance(response, Capture):
                    return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                response, delay = PublicError("fonte_indisponivel", "Falha de conexão com a fonte oficial"), 0
            if response.code not in {"limite_fonte", "fonte_indisponivel"}:
                raise response
            if delay:
                await pace.cooldown(min(delay, 3600))
            if attempt == 2 or delay > 6:
                raise response
            await asyncio.sleep(max(delay, (2**attempt) * 0.4 + random.uniform(0.05, 0.25)))
        raise AssertionError("tentativas esgotadas")

    async def _request(self, method: str, url: str, params: dict | None, headers: dict | None, limit: int):
        async with self.client.stream(method, url, params=params, headers=headers, follow_redirects=False) as res:
            code = res.status_code
            if 300 <= code < 400:
                raise PublicError("redirecionamento_bloqueado", "A fonte respondeu com redirecionamento")
            if code == 429:
                return PublicError("limite_fonte", "A fonte limitou as requisições"), retry_after(
                    res.headers.get("Retry-After")
                )
            if code in {408, 425} or code >= 500:
                return PublicError("fonte_indisponivel", f"A fonte respondeu HTTP {code}"), retry_after(
                    res.headers.get("Retry-After")
                )
            if code in {401, 403}:
                raise PublicError("acesso_negado", f"Acesso à fonte recusado (HTTP {code})")
            if code == 404:
                raise PublicError("nao_encontrado", "Registro ou conjunto não encontrado na fonte")
            if not 200 <= code < 300:
                raise PublicError("filtro_fonte", f"A fonte recusou a consulta (HTTP {code})")
            declared = res.headers.get("Content-Length", "")
            if method != "HEAD" and declared.isdecimal() and int(declared) > limit:
                raise PublicError("resposta_grande", "A resposta excedeu o limite de bytes")
            data = bytearray()
            async for chunk in res.aiter_bytes(chunk_size=65536):
                if len(data) + len(chunk) > limit:
                    raise PublicError("resposta_grande", "A resposta excedeu o limite de bytes")
                data.extend(chunk)
            return Capture(
                str(res.url), bytes(data), res.headers.get("Content-Type", "").split(";")[0].strip().lower(), code
            ), 0
