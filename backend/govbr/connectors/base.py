from dataclasses import dataclass, field
from typing import Any

from govbr.models import Operation, PublicError, Query, Record
from govbr.transport import Capture, SafeHTTP


@dataclass(frozen=True)
class Source:
    id: str
    nome: str
    orgao: str
    esferas: tuple[str, ...]
    uf: str | None
    oficial: str
    documentacao: str
    acesso: str
    formato: str
    autenticacao: str
    atualizacao: str
    limite: str
    restricoes: str
    ttl: int
    capacidades: tuple[Operation, ...] = ()


@dataclass
class Row:
    record: Record
    original: dict[str, Any]


@dataclass
class Page:
    capture: Capture
    rows: list[Row]
    next_page: int | None = None
    total: int | None = None
    warnings: list[str] = field(default_factory=list)
    raw_count: int | None = None
    local: list[str] = field(default_factory=list)


def require(query: Query, *fields: str) -> None:
    missing = [field for field in fields if getattr(query, field) is None]
    if missing:
        raise PublicError("filtros_obrigatorios", "Informe " + ", ".join(missing))


def allow(query: Query, *fields: str) -> None:
    unsupported = set(query.filtros()) - {
        "pagina",
        "limite",
        "valor_minimo",
        "valor_maximo",
        "texto",
        *fields,
    }
    if unsupported:
        raise PublicError(
            "filtro_sem_suporte", "Filtros sem suporte nesta fonte: " + ", ".join(sorted(unsupported))
        )


def interval(query: Query, days: int, fmt: str) -> tuple[str, str]:
    require(query, "data_inicial", "data_final")
    assert query.data_inicial is not None and query.data_final is not None
    if (query.data_final - query.data_inicial).days >= days:
        raise PublicError("intervalo_excedido", f"Período máximo de {days} dias nesta operação")
    return query.data_inicial.strftime(fmt), query.data_final.strftime(fmt)


def items(payload: Any, key: str | None = None) -> list[dict]:
    if key is not None:
        if not isinstance(payload, dict) or key not in payload:
            raise PublicError("schema_fonte", f"A fonte não retornou a lista esperada em {key}")
        payload = payload[key]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise PublicError("schema_fonte", "A fonte não retornou objetos na lista esperada")
    return payload


def object_item(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    raise PublicError("schema_fonte", "Objeto inesperado na resposta da fonte")


class Connector:
    source: Source
    hosts: frozenset[str]
    interval_seconds: float = 0.5

    def __init__(self, http: SafeHTTP):
        self.http = http

    async def get(self, url: str, params: dict | None = None, **kwargs: Any) -> Capture:
        params = {k: v for k, v in params.items() if v is not None} if params else None
        return await self.http.get(url, self.hosts, params=params, interval=self.interval_seconds, **kwargs)

    async def search(self, query: Query) -> Page:
        raise NotImplementedError

    async def health(self) -> Capture:
        raise NotImplementedError


def upstream_window(query: Query, minimum_size: int = 10) -> tuple[int, int, int]:
    pages_in_batch = (max(minimum_size, query.limite) + query.limite - 1) // query.limite
    index = query.pagina - 1
    return index // pages_in_batch + 1, pages_in_batch * query.limite, (index % pages_in_batch) * query.limite


def window_slice(query: Query, rows: list[dict], shift: int, has_more: bool) -> tuple[list[dict], int | None]:
    end = shift + query.limite
    return rows[shift:end], query.pagina + 1 if has_more or end < len(rows) else None
