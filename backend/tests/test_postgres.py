import asyncio
import hashlib
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from govbr.service import GovService
from govbr.settings import ADMIN, READ, Settings
from govbr.transport import SafeHTTP
from govbr.web import create_app

pytestmark = pytest.mark.postgres


@asynccontextmanager
async def lifespan_in_task(app):
    ready, stop = asyncio.Event(), asyncio.Event()

    async def serve():
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(serve())
    wait = asyncio.create_task(ready.wait())
    try:
        await asyncio.wait((task, wait), return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            await task
        yield
    finally:
        stop.set()
        wait.cancel()
        await task


@pytest.fixture
async def suite():
    database = os.getenv("GOVBR_TEST_DATABASE_URL")
    if not database:
        pytest.skip("GOVBR_TEST_DATABASE_URL ausente")
    settings = Settings(database_url=database, public_url="http://localhost:8000", requests_per_minute=100)
    sample = {
        "numeroControlePNCP": "04564530000113-2-000059/2024",
        "objetoContrato": "<img src=x> Aquisição de livros",
        "valorGlobal": "2058500.00",
        "orgaoEntidade": {"cnpj": "04564530000113", "razaoSocial": "Órgão", "esferaId": "E"},
        "unidadeOrgao": {"ufSigla": "RO", "codigoIbge": "1100205"},
        "dataPublicacaoPncp": "2025-01-02T03:45:00",
    }
    probe = str(uuid4())
    sample["objetoContrato"] += f" {probe}"
    seen = []

    def upstream(request):
        seen.append(request.url.path)
        if "/arquivos/" in request.url.path:
            return httpx.Response(200, content=b"%PDF-1.7\n teste", headers={"Content-Type": "application/pdf"})
        if "/arquivos" in request.url.path:
            return httpx.Response(200, json=[{"titulo": "Contrato", "sequencialDocumento": 1}])
        return httpx.Response(200, json=sample)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream), trust_env=False) as upstream_client:
        service = GovService(settings, http=SafeHTTP(settings, client=upstream_client, check_dns=False))
        app = create_app(settings, service)
        async with lifespan_in_task(app):
            a = await service.db.key_add("teste admin", [READ, ADMIN], "test")
            b = await service.db.key_add("teste leitura", [READ], "test")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=settings.public_url, trust_env=False
            ) as client:
                yield (
                    client,
                    service,
                    {"Authorization": f"Bearer {a['token']}"},
                    {"Authorization": f"Bearer {b['token']}"},
                    seen,
                    probe,
                )


async def test_access_cache_history_investigation_and_evidence(suite):
    client, service, admin, reader, seen, probe = suite
    skip = await client.get("/api/me")
    assert skip.status_code == 401
    assert (await client.get("/readyz")).json()["migracao"] == "0002"
    denied = await client.get("/api/admin/chaves", headers=reader)
    assert denied.status_code == 403
    assert (await client.get("/api/admin/chaves", headers=admin)).status_code == 200
    body = {
        "operacao": "contrato",
        "fonte": "pncp",
        "identificador": "04564530000113-2-000059/2024",
        "texto": probe,
    }
    sent = await client.post("/api/consultas", headers=admin, json=body)
    assert sent.status_code == 200
    first = sent.json()
    assert first["estado"] == "ok" and first["registros"][0]["titulo"] == f"Aquisição de livros {probe}"
    assert first["fontes"][0]["cache"] is False
    second = (await client.post("/api/consultas", headers=admin, json=body)).json()
    assert second["fontes"][0]["cache"] is True
    assert second["registros"][0]["evidencia_id"] == first["registros"][0]["evidencia_id"]
    assert len(seen) == 1
    item = first["consulta_id"]
    assert (await client.get(f"/api/consultas/{item}", headers=reader)).status_code == 404
    assert (await client.get(f"/api/consultas/{item}", headers=admin)).status_code == 200
    res = await client.get(f"/api/consultas/{item}/exportar?formato=csv", headers=admin)
    assert "Aquisição de livros" in res.text and res.headers["Content-Disposition"].startswith("attachment")
    ev = first["registros"][0]["evidencia_id"]
    detail = (await client.get(f"/api/evidencias/{ev}", headers=admin)).json()
    assert detail["url"].startswith("https://pncp.gov.br/") and len(detail["sha256"]) == 64
    case = (await client.post("/api/investigacoes", headers=admin, json={"title": "Teste de vínculo"})).json()[
        "id"
    ]
    assert (
        await client.post(f"/api/investigacoes/{case}/consultas", headers=admin, json={"consulta_id": item})
    ).status_code == 200
    assert (
        await client.put(f"/api/investigacoes/{case}", headers=reader, json={"title": "Alheia"})
    ).status_code == 404
    assert (await client.get("/api/investigacoes", headers=admin)).json()[0]["queries"] == [item]


async def test_documents_are_attachments_and_hashed(suite):
    client, _, admin, _, _, _ = suite
    form = {"operacao": "documentos", "fonte": "pncp", "identificador": "04564530000113-2-000059/2024"}
    data = (await client.post("/api/consultas", headers=admin, json=form)).json()
    evidence = data["registros"][0]["evidencia_id"]
    original = await client.get(f"/api/evidencias/{evidence}/pdf", headers=admin)
    assert original.status_code == 200
    assert original.headers["Content-Disposition"].startswith("attachment")
    assert original.headers["X-Content-SHA256"] == hashlib.sha256(original.content).hexdigest()
    assert original.headers["X-Content-Type-Options"] == "nosniff"


async def test_api_only_contract_and_streamed_body_limit(suite):
    client, _, admin, reader, seen, _ = suite
    home = (await client.get("/")).json()
    spec = (await client.get(home["openapi"])).json()
    assert spec["info"]["version"] == home["versao"]
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert spec["paths"]["/api/consultas"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "/api/admin/jobs" not in spec["paths"]
    assert (await client.get("/api/admin/jobs", headers=admin)).status_code == 404
    assert (await client.get("/api/cobertura", headers=reader)).status_code == 404
    sources = (await client.get("/api/fontes", headers=reader)).json()
    assert {"pncp", "siconfi", "compras", "ibge", "dados_pb", "cgu"} <= {source["id"] for source in sources}
    assert "tce_pb" not in {source["id"] for source in sources}

    async def large_body():
        yield b" " * 33000
        yield b" " * 33000

    res = await client.post(
        "/api/consultas",
        headers={**reader, "Content-Type": "application/json"},
        content=large_body(),
    )
    assert res.status_code == 413
    assert "Content-Length" not in res.request.headers
    assert not seen


async def test_mcp_discovery_and_scope(suite):
    client, _, _, reader, _, _ = suite
    missing = await client.post("/mcp", json={})
    assert missing.status_code == 401
    headers = {**reader, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    setup = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "tester", "version": "1"},
        },
    }
    init = await client.post("/mcp", headers=headers, json=setup)
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "GovBR MCP"
    doc = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    payload = (await client.post("/mcp", headers=headers, json=doc)).json()
    assert len(payload["result"]["tools"]) >= 25
    call = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "gov_consultar_contrato",
            "arguments": {"filtros": {"identificador": "04564530000113-2-000059/2024"}},
        },
    }
    output = (await client.post("/mcp", headers=headers, json=call)).json()["result"]["structuredContent"]
    assert output["registros"] and output["estado"] == "ok"
    assert (await client.get(f"/api/consultas/{output['consulta_id']}", headers=reader)).status_code == 200
    assert (
        await client.post("/mcp", headers={**headers, "Origin": "https://evil.test"}, json=setup)
    ).status_code >= 400
