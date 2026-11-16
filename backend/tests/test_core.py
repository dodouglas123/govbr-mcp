from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from govbr.connectors.base import upstream_window, window_slice
from govbr.connectors.pncp import _pncp_row
from govbr.models import Operation, Query, Record, SourceResult, cnpj
from govbr.normalize import clean_text, money, pncp_parts, search_key
from govbr.service import overall_status, reconcile
from govbr.settings import Settings
from govbr.web import csv_cell


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00.000.000/0001-91", "00000000000191"),
        ("12.abc.345/01de-35", "12ABC34501DE35"),
    ],
)
def test_cnpj(raw, expected):
    assert cnpj(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "00000000000000",
        "12ABC34501DE34",
        "0000000000191",
        "000.000.000-00",
        "０００００００００００１９１",
        "00000000000191;",
    ],
)
def test_cnpj_invalid(raw):
    with pytest.raises(ValueError):
        cnpj(raw)


@pytest.mark.parametrize(
    "filters",
    [
        {"uf": "PE", "codigo_ibge": 2507507},
        {"data_inicial": "2024-01-01"},
        {"data_inicial": "2025-03-01", "data_final": "2025-02-01"},
        {"valor_minimo": "10.1", "valor_maximo": "9.5"},
        {"pagina": 0},
        {"identificador": "https://169.254.169.254/"},
        {"codigo_orgao": "1'; DROP TABLE sources;--"},
        {"qq": "arbitrário"},
        {"valor_minimo": "NaN"},
        {"uf": "AD"},
        {"codigo_ibge": 5500000},
    ],
)
def test_filters(filters):
    with pytest.raises(ValidationError):
        Query(operacao="contratos", **filters)


def test_financial_number():
    assert money("1.234.567,89", locale="pt-BR") == Decimal("1234567.89")
    assert money("5.712", locale="pt-BR") == Decimal("5712")
    assert money("-112,1", locale="pt-BR") == Decimal("-112.1")
    assert money("12.34", locale="pt-BR") is None
    assert money("NaN") is None
    assert money(True) is None
    assert money("12.34") == Decimal("12.34")


def test_pncp_id():
    assert pncp_parts("04564530000113-2-000059/2024") == ("04564530000113", "2", 2024, 59)
    with pytest.raises(ValueError):
        pncp_parts("example.com/foo")


@pytest.mark.parametrize("size", [1, 3, 7, 10, 19, 50])
def test_windows_no_skipped_records(size):
    records = [{"id": i} for i in range(57)]
    number = 1
    mined = []
    while number:
        q = Query(operacao="contratos", limite=size, pagina=number)
        upstream, batchsize, shift = upstream_window(q)
        upstream_rows = records[(upstream - 1) * batchsize : upstream * batchsize]
        sliced, number = window_slice(q, upstream_rows, shift, upstream * batchsize < len(records))
        mined.extend(sliced)
    assert mined == records


def test_same_pncp_key_is_reconciled_and_conflicting_values_survive_as_evidence():
    base = dict(
        conjunto="contratos",
        id_original="1",
        tipo="contrato",
        titulo="Objeto",
        url_oficial="https://pncp.gov.br",
        identificadores={"pncp": "04564530000113-2-000059/2024"},
    )
    left = Record(**base, fonte="pncp", valor=Decimal("4.10"), evidencia_id=uuid4())
    right = Record(**base, fonte="compras", valor=Decimal("6.00"), evidencia_id=uuid4())
    other = Record(**{**base, "identificadores": {}}, fonte="cgu", valor=Decimal("4.10"))
    records, relations, changes = reconcile([left, right, other])
    assert [r.fonte for r in records] == ["pncp", "cgu"]
    assert relations[0]["confianca"] == "confirmada"
    assert changes[0]["campos"]["valor"] == ["4.10", "6.00"]


def test_partial_and_empty_are_distinct():
    results = [SourceResult(fonte="pncp", pagina=1, estado="incompleto", proxima_pagina=2)]
    assert overall_status(results, 0) == "incompleto"
    results.append(SourceResult(fonte="cgu", pagina=1, estado="erro", erro="credencial_ausente"))
    assert overall_status(results, 0) == "parcial"
    assert overall_status([SourceResult(fonte="pb", pagina=1, estado="vazio")], 0) == "vazio"


def test_public_data_sanitized_and_formula_escaped():
    assert clean_text("<img src=x>\x00 João 123.456.789-01") == "João [CPF omitido]"
    assert search_key("João PESSOA") == "joao pessoa"
    assert csv_cell("  =HYPERLINK()") == "'  =HYPERLINK()"
    assert csv_cell("-2.01", numeric=True) == "-2.01"
    row = _pncp_row(
        Operation.CONTRATO,
        {
            "numeroControlePNCP": "04564530000113-2-000059/2024",
            "valorGlobal": "20.25",
            "tipoPessoa": "PF",
            "niFornecedor": "12345678901",
            "nomeRazaoSocialFornecedor": "Nome de pessoa",
            "objetoContrato": "<script>malicioso</script>",
        },
    )
    assert row and row.record.cnpj is None and "Nome de pessoa" not in str(row.original)
    assert row.record.valor == Decimal("20.25")


def test_tls_config_configuration():
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(environment="production")
    with pytest.raises(ValidationError, match="audiência"):
        Settings(
            public_url="https://gov.example",
            oauth_issuer="https://id.example",
            oauth_jwks_url="https://id.example/jwks",
            oauth_audience="other",
        )
    assert Settings().resource.endswith("/mcp")


def test_time_has_timezone():
    outcome = SourceResult(fonte="pncp", estado="ok", pagina=1, consultado_em=datetime.now(UTC))
    assert outcome.model_dump(mode="json")["consultado_em"].endswith("Z")
