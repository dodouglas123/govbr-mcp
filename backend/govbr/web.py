from __future__ import annotations

import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi import Query as HttpQuery
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import Response as HttpResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mcp.server.transport_security import TransportSecuritySettings
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as upsert
from starlette.types import ASGIApp, Receive, Scope, Send

from govbr import __version__
from govbr import schema as s
from govbr.auth import Authorization, McpGate, Principal
from govbr.mcp_server import build_mcp
from govbr.models import UF, Ano, PublicError, Query, Response, utcnow
from govbr.service import GovService
from govbr.settings import ADMIN, READ, Settings

log = logging.getLogger("govbr.web")
bearer = HTTPBearer(auto_error=False)


class LimitApiBody:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/")
            or scope["method"] not in {"POST", "PUT"}
        ):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > 65536:
                await JSONResponse({"erro": "corpo_grande"}, status_code=413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body"):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


async def clean_expired(service: GovService):
    while True:
        try:
            await service.db.cleanup()
        except Exception as exc:
            log.warning("limpeza_banco tipo=%s", type(exc).__name__)
        await asyncio.sleep(300)


class NewKey(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    admin: bool = False


class SourceSettings(BaseModel):
    enabled: bool
    ttl: Annotated[int, Field(ge=0, le=86400)] | None = None


class CaseInput(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    notes: Annotated[str, StringConstraints(max_length=4000)] = ""
    status: Literal["aberta", "concluida"] = "aberta"


class AttachInput(BaseModel):
    consulta_id: UUID


class CompareInput(BaseModel):
    uf_a: UF
    uf_b: UF
    ano: Ano
    funcao: Literal["06", "10", "12"]
    fase: Literal["empenhada", "liquidada", "paga"]


def create_app(settings: Settings | None = None, service: GovService | None = None) -> FastAPI:
    settings = settings or Settings()
    service = service or GovService(settings)
    auth = Authorization(service.db, service.http)
    origin, resources = settings.public_url, [urlsplit(settings.public_url).netloc]
    if urlsplit(origin).hostname in {"localhost", "127.0.0.1"}:
        port = urlsplit(origin).port or 80
        resources.extend([f"localhost:{port}", f"127.0.0.1:{port}"])
    mcp = build_mcp(service).streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=65536,
        transport_security=TransportSecuritySettings(allowed_hosts=list(set(resources)), allowed_origins=[origin]),
    )

    @asynccontextmanager
    async def lifespan(app):
        try:
            await service.db.ping()
            await service.db.seed()
            async with mcp.router.lifespan_context(mcp):
                cleanup = asyncio.create_task(clean_expired(service))
                try:
                    yield
                finally:
                    cleanup.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup
        finally:
            await service.close()

    app = FastAPI(
        title="GovBR MCP · API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(LimitApiBody)

    async def authenticated(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        principal = await auth.verify(f"Bearer {credentials.credentials}" if credentials else None)
        if principal is None:
            raise HTTPException(401, "Chave de acesso inválida", headers={"WWW-Authenticate": auth.challenge()})
        if READ not in principal.scopes:
            raise HTTPException(403, "Escopo de leitura ausente")
        if not await service.db.throttle(principal.actor):
            raise HTTPException(429, "Limite de consultas do usuário excedido", headers={"Retry-After": "60"})
        return principal

    async def admin(principal: Principal = Depends(authenticated)) -> Principal:
        if ADMIN not in principal.scopes:
            raise HTTPException(403, "Escopo administrativo ausente")
        return principal

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        if request.url.path.startswith(("/api/", "/.well-known/")):
            length = request.headers.get("content-length", "")
            if length.isdecimal() and int(length) > 65536:
                return JSONResponse({"erro": "corpo_grande"}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith(("/api/", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(PublicError)
    async def public_error(request: Request, exc: PublicError):
        status = 404 if exc.code.endswith(("_inexistente", "_inativa", "_inativo")) else 400
        return JSONResponse({"erro": exc.code, "mensagem": str(exc)}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def bad_input(request: Request, exc: RequestValidationError):
        errors = [{"campo": ".".join(map(str, e["loc"])), "mensagem": e["msg"]} for e in exc.errors()]
        return JSONResponse({"erro": "filtros_invalidos", "campos": errors}, status_code=422)

    @app.exception_handler(TimeoutError)
    async def request_timeout(request: Request, exc: Exception):
        return JSONResponse({"erro": "timeout", "mensagem": "Prazo da operação excedido"}, status_code=504)

    @app.get("/")
    async def index():
        return {"projeto": "GovBR MCP", "versao": __version__, "openapi": "/api/openapi.json", "mcp": "/mcp"}

    @app.get("/healthz")
    async def live():
        return {"estado": "ok"}

    @app.get("/readyz")
    async def ready():
        try:
            rev = await service.db.ping()
        except Exception as exc:
            log.warning("prontidao_banco tipo=%s", type(exc).__name__)
            return JSONResponse({"estado": "indisponivel"}, status_code=503)
        if rev != "0002":
            return JSONResponse({"estado": "migracao_pendente"}, status_code=503)
        return {"estado": "ok", "versao": __version__, "migracao": rev}

    @app.get("/.well-known/oauth-protected-resource/mcp")
    @app.get("/.well-known/oauth-protected-resource")
    async def resource_metadata():
        return auth.metadata()

    @app.get("/api/me")
    async def me(principal: Principal = Depends(authenticated)):
        return {"id": principal.actor, "scopes": sorted(principal.scopes), "mcp": settings.resource}

    @app.get("/api/fontes")
    async def list_sources(principal: Principal = Depends(authenticated)):
        return await service.sources()

    @app.post("/api/fontes/{source}/verificar")
    async def check_source(source: str, principal: Principal = Depends(authenticated)):
        return await service.health(source)

    @app.put("/api/fontes/{source}")
    async def configure_source(source: str, config: SourceSettings, principal: Principal = Depends(admin)):
        if source not in service.connectors:
            raise PublicError("fonte_inexistente", "Fonte ainda não implementada")
        await service.db.source_config(source, config.enabled, config.ttl, principal.actor)
        return {"estado": "atualizado"}

    @app.post("/api/consultas", response_model=Response)
    async def query(q: Query, principal: Principal = Depends(authenticated)):
        return await service.query(principal.actor, q)

    @app.post("/api/comparar", response_model=Response)
    async def compare(q: CompareInput, principal: Principal = Depends(authenticated)):
        return await service.compare(principal.actor, **q.model_dump())

    @app.get("/api/consultas")
    async def history(
        offset: Annotated[int, HttpQuery(ge=0, le=10000)] = 0, principal: Principal = Depends(authenticated)
    ):
        return await service.db.history_list(principal.actor, offset)

    @app.get("/api/consultas/{id_}")
    async def query_detail(id_: UUID, principal: Principal = Depends(authenticated)):
        return await service.db.query_detail(principal.actor, id_)

    @app.get("/api/consultas/{id_}/exportar")
    async def export(
        id_: UUID, formato: Literal["csv", "json"] = "json", principal: Principal = Depends(authenticated)
    ):
        item = await service.db.query_detail(principal.actor, id_)
        if formato == "json":
            return JSONResponse(
                jsonable_encoder(item), headers={"Content-Disposition": f'attachment; filename="{id_}.json"'}
            )
        columns = (
            "fonte",
            "conjunto",
            "id_original",
            "tipo",
            "titulo",
            "esfera",
            "uf",
            "codigo_ibge",
            "cnpj",
            "orgao",
            "valor",
            "moeda",
            "natureza_valor",
            "data_publicacao",
            "competencia",
            "url_oficial",
            "evidencia_id",
        )
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for record in item["response"]["registros"]:
            writer.writerow({key: csv_cell(record.get(key), key == "valor") for key in columns})
        return HttpResponse(
            "\ufeff" + buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{id_}.csv"'},
        )

    @app.get("/api/evidencias/{id_}")
    async def evidence(id_: UUID, principal: Principal = Depends(authenticated)):
        return await service.db.evidence_detail(id_)

    @app.get("/api/evidencias/{id_}/pdf")
    async def pdf(
        id_: UUID,
        sha256: Annotated[str, HttpQuery(pattern=r"^[0-9a-f]{64}$")] | None = None,
        principal: Principal = Depends(authenticated),
    ):
        item = await service.document_download(id_, sha256)
        return HttpResponse(
            item["content"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="pncp-{id_}.pdf"',
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-SHA256": item["sha256"],
            },
        )

    @app.get("/api/dashboard")
    async def dashboard(principal: Principal = Depends(authenticated)):
        sources = await service.sources()
        return {
            **await service.db.stats(principal.actor),
            "fontes_operacionais": sum(i["estado"] == "operacional" for i in sources),
            "fontes": sources,
            "recentes": await service.db.history_list(principal.actor, limit=6),
        }

    @app.get("/api/investigacoes")
    async def case_list(principal: Principal = Depends(authenticated)):
        t, association = s.investigations, s.investigation_queries
        async with service.db.engine.connect() as db:
            items = (
                (
                    await db.execute(
                        select(t).where(t.c.actor == principal.actor).order_by(t.c.updated_at.desc()).limit(100)
                    )
                )
                .mappings()
                .all()
            )
            if not items:
                return []
            links = (
                (
                    await db.execute(
                        select(association).where(
                            association.c.investigation_id.in_(
                                [row["id"] for row in items],
                            )
                        )
                    )
                )
                .mappings()
                .all()
            )
        lookup = {}
        for row in links:
            lookup.setdefault(row["investigation_id"], []).append(row["query_id"])
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "notes": row["notes"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "queries": lookup.get(row["id"], []),
            }
            for row in items
        ]

    @app.post("/api/investigacoes", status_code=201)
    async def case_new(case: CaseInput, principal: Principal = Depends(authenticated)):
        id_ = uuid4()
        async with service.db.engine.begin() as db:
            await db.execute(
                insert(s.investigations).values(
                    id=id_,
                    actor=principal.actor,
                    updated_at=utcnow(),
                    **case.model_dump(),
                )
            )
        return {"id": id_}

    @app.put("/api/investigacoes/{id_}")
    async def case_update(id_: UUID, case: CaseInput, principal: Principal = Depends(authenticated)):
        async with service.db.engine.begin() as db:
            await check_case(db, principal.actor, id_)
            await db.execute(
                update(s.investigations)
                .where(s.investigations.c.id == id_)
                .values(
                    updated_at=utcnow(),
                    **case.model_dump(),
                )
            )
        return {"id": id_}

    @app.post("/api/investigacoes/{id_}/consultas")
    async def case_attach(id_: UUID, input_: AttachInput, principal: Principal = Depends(authenticated)):
        async with service.db.engine.begin() as db:
            await check_case(db, principal.actor, id_)
            owned = await db.scalar(
                select(s.history.c.id)
                .where(
                    s.history.c.actor == principal.actor,
                    s.history.c.id == input_.consulta_id,
                )
                .with_for_update(read=True)
            )
            if not owned:
                raise PublicError("consulta_inexistente", "Consulta expirada ou fora do seu histórico")
            await db.execute(
                upsert(s.investigation_queries)
                .values(
                    investigation_id=id_,
                    query_id=input_.consulta_id,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(
                update(s.investigations).where(s.investigations.c.id == id_).values(updated_at=utcnow())
            )
        return {"id": id_, "consulta_id": input_.consulta_id}

    @app.get("/api/admin/chaves")
    async def keys(principal: Principal = Depends(admin)):
        return await service.db.key_list()

    @app.post("/api/admin/chaves", status_code=201)
    async def add_key(key: NewKey, principal: Principal = Depends(admin)):
        return await service.db.key_add(key.label, [READ, ADMIN] if key.admin else [READ], principal.actor)

    @app.delete("/api/admin/chaves/{id_}")
    async def revoke_key(id_: UUID, principal: Principal = Depends(admin)):
        if principal.actor == f"token:{id_}":
            raise PublicError("chave_em_uso", "Use outra chave administrativa para revogar a chave da sessão")
        await service.db.key_revoke(id_, principal.actor)
        return {"estado": "revogada"}

    @app.get("/api/admin/config")
    async def config(principal: Principal = Depends(admin)):
        return {
            "cgu_configurada": bool(settings.cgu_key and settings.cgu_key.get_secret_value().strip()),
            "oauth_configurado": bool(settings.oauth_issuer),
            "requests_per_minute": settings.requests_per_minute,
            "query_concurrency": settings.query_concurrency,
            "history_days": settings.history_days,
            "evidence_days": settings.evidence_days,
            "document_max_mib": settings.document_max_mib,
        }

    @app.get("/api/admin/auditoria")
    async def events(principal: Principal = Depends(admin)):
        return await service.db.audit_list()

    @app.get("/api/admin/metrics")
    async def metrics(principal: Principal = Depends(admin)):
        return HttpResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.mount("/", McpGate(mcp, auth))
    return app


async def check_case(db, actor: str, id_: UUID):
    t = s.investigations
    if not await db.scalar(select(t.c.id).where(t.c.id == id_, t.c.actor == actor).with_for_update()):
        raise PublicError("investigacao_inexistente", "Investigação inexistente ou de outro usuário")


def csv_cell(value, numeric: bool = False):
    if not isinstance(value, str) or numeric:
        return value
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
        else value
    )
