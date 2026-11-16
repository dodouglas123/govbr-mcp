import asyncio

import httpx
import pytest

from govbr.connectors.cgu import Cgu
from govbr.connectors.pncp import Pncp
from govbr.connectors.siconfi import Siconfi
from govbr.models import PublicError, Query
from govbr.settings import Settings
from govbr.transport import SafeHTTP

HOSTS = frozenset({"pncp.gov.br"})


@pytest.mark.parametrize(
    "url",
    [
        "http://pncp.gov.br/a",
        "https://pncp.gov.br.evil.test/a",
        "https://pncp.gov.br@127.0.0.1/",
        "https://pncp.gov.br:8443/a",
        "https://127.0.0.1/",
        "https://pncp.gov.br/a#b",
        "https://pncp.gov.br\\evil.test/",
    ],
)
def test_ssrf_origins(url):
    with pytest.raises(PublicError, match="origens oficiais"):
        SafeHTTP.validate_url(url, HOSTS)


async def test_dns_private_address_rejected(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(None, None, None, "", ("169.254.169.254", 443))]

    async with httpx.AsyncClient(trust_env=False) as client:
        outbound = SafeHTTP(Settings(), client=client)
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        with pytest.raises(PublicError, match="endereço não público"):
            await outbound.get("https://pncp.gov.br/teste", HOSTS)


async def test_429_retries_and_no_redirect():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:5432/"})
        if count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outbound = SafeHTTP(Settings(), client=client, check_dns=False)
        assert (await outbound.get("https://pncp.gov.br/teste", HOSTS, interval=0)).json() == {"ok": True}
        assert count == 2
        with pytest.raises(PublicError, match="redirecionamento"):
            await outbound.get("https://pncp.gov.br/redirect", HOSTS, interval=0)
        assert count == 3


async def test_timeout_retries_only_three_times():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ConnectTimeout("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outbound = SafeHTTP(Settings(), client=client, check_dns=False)
        with pytest.raises(PublicError, match="Falha de conexão"):
            await outbound.get("https://pncp.gov.br/teste", HOSTS, interval=0)
    assert count == 3


async def test_cgu_missing_key_no_external_http():
    def handler(request):
        pytest.fail("requisição sem credencial")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = Cgu(SafeHTTP(Settings(), client=client, check_dns=False), None)
        with pytest.raises(PublicError) as error:
            await source.search(Query(operacao="sancoes", cnpj="00000000000191"))
    assert error.value.code == "credencial_ausente"


async def test_pncp_native_does_not_send_unsupported_filter():
    def handler(request):
        params = request.url.params
        assert "uf" not in params and "niFornecedor" not in params
        return httpx.Response(200, json={"data": [], "totalPaginas": 4, "totalRegistros": 37})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = Pncp(SafeHTTP(Settings(), client=client, check_dns=False))
        page = await source.search(
            Query(
                operacao="contratos",
                uf="PB",
                cnpj="00000000000191",
                limite=10,
                data_inicial="2025-01-02",
                data_final="2025-01-02",
            )
        )
    assert page.next_page == 2 and page.local == ["uf", "cnpj"]


async def test_siconfi_rejects_drift_and_paginates():
    def handler(req):
        assert req.url.params["offset"] == "5"
        return httpx.Response(200, json={"items": [{}], "pageCount": 4})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = Siconfi(SafeHTTP(Settings(), client=client, check_dns=False))
        with pytest.raises(PublicError) as error:
            await source.search(Query(operacao="fiscais", codigo_ibge=2507507, ano=2024, limite=5, pagina=2))
    assert error.value.code == "schema_fonte"


async def test_pncp_ata_uses_parent_identifier_and_preserves_suffix():
    def handler(request):
        assert request.url.path.endswith("/15126437000305/compras/2025/2417/atas")
        assert request.url.params["pagina"] == "1"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "numeroControlePNCP": "15126437000305-1-002417/2025-000001",
                        "numeroAtaRegistroPreco": "00890",
                        "sequencialAta": 1,
                        "orgaoEntidade": {
                            "cnpj": "15126437000305",
                            "esferaId": "N",
                            "razaoSocial": "Órgão oficial",
                        },
                        "unidadeOrgao": {"codigoIbge": "2507507", "ufSigla": "PB"},
                    }
                ],
                "totalRegistros": 1,
                "totalPaginas": 1,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = Pncp(SafeHTTP(Settings(), client=client, check_dns=False))
        page = await source.search(Query(operacao="atas", identificador="15126437000305-1-002417/2025"))
    [row] = page.rows
    assert row.record.identificadores["licitacao_pncp"] == "15126437000305-1-002417/2025"
    assert row.record.id_original.endswith("-000001") and row.record.url_oficial.endswith("/atas/1")
