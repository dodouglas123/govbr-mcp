from __future__ import annotations

import asyncio
import hashlib
import re
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.routes import build_resource_metadata_url
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from govbr.models import PublicError
from govbr.settings import READ
from govbr.storage import Store
from govbr.transport import SafeHTTP

STDIO_ACTOR = "local:stdio"
PAT = re.compile(r"govbr_[A-Za-z0-9_-]{48}\Z")
BEARER = re.compile(r"Bearer ([A-Za-z0-9._~+/-]{1,8192}={0,2})\Z", re.IGNORECASE)


@dataclass(frozen=True)
class Principal:
    actor: str
    scopes: frozenset[str]


current_actor: ContextVar[str] = ContextVar("govbr_actor", default=STDIO_ACTOR)


class Authorization:
    def __init__(self, db: Store, http: SafeHTTP):
        self.db = db
        self.config = db.settings
        self.http = http
        self.lock = asyncio.Lock()
        self.keys: dict[str, jwt.PyJWK] = {}
        self.refresh_at = 0.0
        self.retry_at = 0.0

    def challenge(self, code: str = "invalid_token") -> str:
        values = [f'Bearer realm="GovBR MCP", error="{code}", scope="{READ}"']
        if self.config.oauth_issuer:
            meta = build_resource_metadata_url(self.config.resource)
            values.append(f'resource_metadata="{meta}"')
        return ", ".join(values)

    def metadata(self) -> dict:
        if not self.config.oauth_issuer:
            raise PublicError("oauth_inativo", "Servidor configurado para chaves individuais")
        return {
            "resource": self.config.resource,
            "authorization_servers": [self.config.oauth_issuer],
            "scopes_supported": [READ],
            "bearer_methods_supported": ["header"],
        }

    async def verify(self, header: str | None) -> Principal | None:
        match = BEARER.fullmatch(header or "")
        if not match:
            return None
        token = match.group(1)
        if PAT.fullmatch(token):
            key = await self.db.key_read(token)
            return Principal(f"token:{key['id']}", frozenset(key["scopes"])) if key else None
        if self.config.oauth_issuer and token.count(".") == 2:
            return await self.verify_oauth(token)
        return None

    async def verify_oauth(self, token: str) -> Principal | None:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 200:
                return None
            if header.get("alg") != self.config.oauth_algorithms:
                return None
            key = await self.jwk(kid)
            if not key:
                return None
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[self.config.oauth_algorithms],
                audience=self.config.oauth_audience,
                issuer=self.config.oauth_issuer,
                options={"require": ["aud", "iss", "exp", "sub"]},
            )
        except (jwt.PyJWTError, PublicError, ValueError):
            return None
        scopes = claims.get("scope", "")
        if not isinstance(scopes, str) or not isinstance(claims["sub"], str):
            return None
        allowed = self.config.oauth_allowed_subjects
        if allowed and claims["sub"] not in allowed.split(","):
            return None
        # OAuth para clientes MCP é sempre de leitura. Administração usa chaves
        # emitidas na instalação, escopadas e revogáveis, fora dos clientes de IA.
        actor = hashlib.sha256(f"{claims['iss']}\0{claims['sub']}".encode()).hexdigest()
        return Principal(f"oauth:{actor}", frozenset({READ} & set(scopes.split())))

    async def jwk(self, kid: str):
        async with self.lock:
            now = monotonic()
            if self.refresh_at > now and (kid in self.keys or self.retry_at > now):
                return self.keys.get(kid)
            if self.retry_at > now:
                return None
            self.retry_at = now + 30
            url = self.config.oauth_jwks_url
            assert url
            domain = urlsplit(url).hostname
            assert domain
            async with asyncio.timeout(5):
                res = await self.http.get(url, frozenset({domain}), bytes_limit=128 * 1024)
            obj = res.json()
            if not isinstance(obj, dict) or not isinstance(obj.get("keys"), list) or len(obj["keys"]) > 40:
                return None
            keys = {}
            for entry in obj["keys"]:
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("kid"), str)
                    and entry.get("use") in {None, "sig"}
                ):
                    try:
                        key = jwt.PyJWK.from_dict(entry, algorithm=self.config.oauth_algorithms)
                        keys[key.key_id] = key
                    except (jwt.PyJWTError, ValueError):
                        continue
            self.keys = keys
            self.refresh_at = now + 300
            return keys.get(kid)


class McpGate:
    def __init__(self, app, auth: Authorization):
        self.app, self.auth = app, auth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        try:
            principal = await self.auth.verify(Headers(scope=scope).get("Authorization"))
        except TimeoutError:
            principal = None
        if principal is None:
            await self.error(scope, receive, send, 401, "credencial_invalida", self.auth.challenge())
        elif READ not in principal.scopes:
            await self.error(
                scope, receive, send, 403, "escopo_insuficiente", self.auth.challenge("insufficient_scope")
            )
        elif not await self.auth.db.throttle(principal.actor):
            await self.error(scope, receive, send, 429, "limite_local")
        else:
            marker = current_actor.set(principal.actor)
            try:
                await self.app(scope, receive, send)
            finally:
                current_actor.reset(marker)

    @staticmethod
    async def error(scope, receive, send, status: int, code: str, challenge: str | None = None):
        headers = {"Cache-Control": "no-store"}
        if challenge:
            headers["WWW-Authenticate"] = challenge
        if status == 429:
            headers["Retry-After"] = "60"
        await JSONResponse({"erro": code}, status_code=status, headers=headers)(scope, receive, send)
