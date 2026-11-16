from govbr.catalog import COMPRAS
from govbr.connectors.base import (
    Connector,
    Page,
    Row,
    allow,
    interval,
    items,
    object_item,
    require,
    upstream_window,
    window_slice,
)
from govbr.connectors.pncp import reference
from govbr.models import Operation as O
from govbr.models import PublicError, Query, Record
from govbr.normalize import canonical_digest, clean_text, corporate_id, epoch_iso, integer, money, selected

BASE = "https://dadosabertos.compras.gov.br"


class Compras(Connector):
    source = COMPRAS
    hosts = frozenset({"dadosabertos.compras.gov.br"})
    interval_seconds = 1.0

    async def health(self):
        cap = await self.get(
            f"{BASE}/modulo-fornecedor/1_consultarFornecedor", {"cnpj": "00000000000191", "ativo": "true"}
        )
        items(cap.json(), "resultado")
        return cap

    async def search(self, query: Query) -> Page:
        page, size, shift = upstream_window(query)
        params = {"pagina": page, "tamanhoPagina": size}
        local: list[str] = []
        if query.operacao == O.FORNECEDOR:
            allow(query, "cnpj")
            require(query, "cnpj")
            path = "modulo-fornecedor/1_consultarFornecedor"
            params.update(cnpj=query.cnpj, ativo="true")
        elif query.operacao == O.CONTRATOS:
            allow(query, "codigo_orgao", "cnpj", "data_inicial", "data_final")
            require(query, "codigo_orgao")
            start, end = interval(query, 366, "%Y-%m-%d")
            path = "modulo-contratos/1_consultarContratos"
            params.update(
                codigoOrgao=query.codigo_orgao,
                niFornecedor=query.cnpj,
                dataVigenciaInicialMin=start,
                dataVigenciaInicialMax=end,
            )
        else:
            allow(query, "codigo_material", "uf", "data_inicial", "data_final")
            require(query, "codigo_material")
            path = "modulo-pesquisa-preco/1_consultarMaterial"
            params.update(tipo="codigoItemCatalogo", codigo=query.codigo_material, estado=query.uf)
            if query.data_inicial:
                start, end = interval(query, 366, "%Y-%m-%d")
                params.update(dataCompraInicio=start, dataCompraFim=end)
        cap = await self.get(f"{BASE}/{path}", params)
        obj = object_item(cap.json())
        pages, total = integer(obj.get("totalPaginas")), integer(obj.get("totalRegistros"))
        if pages is None or total is None:
            raise PublicError("schema_fonte", "Compras.gov.br sem metadados de paginação")
        raw, next_page = window_slice(query, items(obj, "resultado"), shift, page < pages)
        rows = [mapped for entry in raw if (mapped := normalize(query.operacao, entry, cap.url))]
        warnings = (
            ["Contratos filtrados pela data de início da vigência."] if query.operacao == O.CONTRATOS else []
        )
        if len(rows) != len(raw):
            warnings.append(f"{len(raw) - len(rows)} registros sem chave verificável")
        return Page(cap, rows, next_page, total, warnings, len(raw), local)


def normalize(operation: O, entry: dict, url: str) -> Row | None:
    if operation == O.FORNECEDOR:
        cnpj = corporate_id(entry.get("cnpj"))
        if not cnpj:
            return None
        props = selected(
            entry,
            (
                "nomeRazaoSocialFornecedor",
                "naturezaJuridicaNome",
                "porteEmpresaNome",
                "nomeCnae",
                "codigoCnae",
                "habilitadoLicitar",
                "ativo",
                "ufSigla",
            ),
        )
        return Row(
            Record(
                fonte=COMPRAS.id,
                conjunto="fornecedores",
                id_original=cnpj,
                tipo="fornecedor",
                cnpj=cnpj,
                titulo=clean_text(entry.get("nomeRazaoSocialFornecedor")) or cnpj,
                uf=clean_text(entry.get("ufSigla"), 2),
                atributos=props,
                url_oficial=url,
            ),
            {"cnpj": cnpj, **props},
        )
    cnpj = corporate_id(entry.get("niFornecedor"))
    if operation == O.CONTRATOS:
        pncp = reference(entry.get("numeroControlePncpContrato"))
        refs = selected(entry, ("codigoOrgao", "codigoUnidadeGestora", "numeroContrato", "processo"))
        if not pncp and not all(refs.get(k) for k in ("codigoOrgao", "codigoUnidadeGestora", "numeroContrato")):
            return None
        identifier = pncp or canonical_digest(refs)
        amount = money(entry.get("valorGlobal"))
        identifiers = {k: str(v) for k, v in refs.items() if v is not None}
        if pncp:
            identifiers["pncp"] = pncp
        if related := reference(entry.get("numeroControlePncpCompra")):
            identifiers["licitacao_pncp"] = related
        props = selected(
            entry,
            (
                "nomeOrgao",
                "objeto",
                "dataVigenciaInicial",
                "dataVigenciaFinal",
                "contratoExcluido",
                "receitaDespesa",
                "valorGlobal",
                "numeroControlePncpContrato",
                "numeroControlePncpCompra",
            ),
        )
        if cnpj:
            props.update(
                niFornecedor=cnpj, nomeRazaoSocialFornecedor=clean_text(entry.get("nomeRazaoSocialFornecedor"))
            )
        return Row(
            Record(
                fonte=COMPRAS.id,
                conjunto="contratos",
                id_original=identifier,
                tipo="contrato",
                titulo=clean_text(entry.get("objeto")) or identifier,
                cnpj=cnpj,
                orgao=clean_text(entry.get("nomeOrgao")),
                valor=amount,
                moeda="BRL" if amount is not None else None,
                natureza_valor="valor_global_contrato",
                competencia=epoch_iso(entry.get("dataVigenciaInicial")),
                url_oficial=url,
                identificadores=identifiers,
                atributos=props,
            ),
            {**refs, **props},
        )
    item, purchase = clean_text(entry.get("idItemCompra"), 120), clean_text(entry.get("idCompra"), 120)
    if not item or not purchase:
        return None
    props = selected(
        entry,
        (
            "idCompra",
            "idItemCompra",
            "codigoItemCatalogo",
            "quantidade",
            "precoUnitario",
            "nomeUnidadeFornecimento",
            "nomeUnidadeMedida",
            "capacidadeUnidadeFornecimento",
            "dataCompra",
            "dataResultado",
            "descricaoItem",
            "codigoMunicipio",
            "estado",
            "nomeOrgao",
            "esfera",
        ),
    )
    amount = money(entry.get("precoUnitario"))
    if cnpj:
        props.update(niFornecedor=cnpj, nomeFornecedor=clean_text(entry.get("nomeFornecedor")))
    return Row(
        Record(
            fonte=COMPRAS.id,
            conjunto="precos_materiais",
            id_original=f"{purchase}:{item}",
            tipo="preco_unitario_observado",
            titulo=clean_text(entry.get("descricaoItem")) or item,
            cnpj=cnpj,
            uf=clean_text(entry.get("estado"), 2),
            codigo_ibge=integer(entry.get("codigoMunicipio")),
            orgao=clean_text(entry.get("nomeOrgao")),
            valor=amount,
            moeda="BRL" if amount is not None else None,
            natureza_valor="preco_unitario",
            competencia=epoch_iso(entry.get("dataCompra")),
            url_oficial=url,
            atributos=props,
            identificadores={"compra_siasg": purchase, "item_siasg": item},
        ),
        props,
    )
