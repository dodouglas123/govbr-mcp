from __future__ import annotations

import re

from govbr.catalog import PB
from govbr.connectors.base import Connector, Page, Row, allow, items, object_item
from govbr.connectors.pncp import reference
from govbr.models import Operation as O
from govbr.models import PublicError, Query, Record
from govbr.normalize import (
    canonical_digest,
    clean_text,
    corporate_id,
    epoch_iso,
    integer,
    money,
    parse_date,
    selected,
)

BASE = "https://api.dados.pb.gov.br/api/v1"
ROUTES = {
    O.DESPESAS: ("despesas/orcamentarias", "credor", "cnpjOrgao"),
    O.EMPENHOS: ("despesas/notas_empenho", "cpfCnpj", "codigoOrgao"),
    O.LIQUIDACOES: ("despesas/liquidacoes", "cnpjCpfCredor", "codigoOrgao"),
    O.PAGAMENTOS: ("despesas/ordem_cronologica_pagamentos", "cnpjCpfCredor", "cnpjOrgao"),
    O.CONTRATOS: ("compras/contratos", "cpfCnpj", None),
    O.LICITACOES: ("compras/contratacoes", None, None),
    O.RECEITAS: ("receita/receita_orcamentaria", None, None),
}
WARNINGS = {
    O.DESPESAS: "Valores por empenho e classificação. Valores empenhados, liquidados e pagos aparecem em campos distintos.",
    O.EMPENHOS: "Valor do empenho publicado. Anulações e suplementos são campos separados.",
    O.LIQUIDACOES: "A API retorna movimentos de liquidação com campos valorEmpenhado, valorGD e anulações. Nenhum é reclassificado como total liquidado.",
    O.PAGAMENTOS: "Ordem cronológica da competência solicitada. Confira status e data de execução, que pode cair em outro mês.",
    O.CONTRATOS: "O ano refere-se ao início da vigência. Valor total contratual inclui os ajustes publicados no registro.",
    O.LICITACOES: "Consulte o cadastro pelo ano informado. Valor estimado e adjudicado são campos distintos.",
    O.RECEITAS: "Receita realizada no mês por rubrica, órgão e fonte, conforme publicado.",
}
PNCP_LINK = re.compile(r"https://pncp\.gov\.br/app/contratos/([A-Z0-9]{14})/(20[0-9]{2})/([0-9]{1,9})\Z")


class DadosPB(Connector):
    source = PB
    hosts = frozenset({"api.dados.pb.gov.br"})
    interval_seconds = 1.0

    async def health(self):
        cap = await self.get(f"{BASE}/despesas/orcamentarias", {"ano": 2026, "mes": 7, "page": 1, "per_page": 1})
        items(cap.json(), "dados")
        return cap

    async def search(self, q: Query) -> Page:
        route, company_parameter, org_parameter = ROUTES[q.operacao]
        annual = q.operacao in {O.CONTRATOS, O.LICITACOES}
        filters = ["ano", "uf", "esfera"]
        if not annual:
            filters.extend(("periodo", "data_inicial", "data_final"))
        if company_parameter:
            filters.append("cnpj")
        if org_parameter:
            filters.append("cnpj_orgao" if org_parameter == "cnpjOrgao" else "codigo_orgao")
        if q.operacao in {O.CONTRATOS, O.LICITACOES, O.EMPENHOS, O.LIQUIDACOES, O.PAGAMENTOS}:
            filters.append("identificador")
        allow(q, *filters)
        year, month = q.ano, q.periodo
        if q.data_inicial and q.data_final:
            y, m = q.data_inicial.year, q.data_inicial.month
            if (y, m) != (q.data_final.year, q.data_final.month) or (year and year != y) or (month and month != m):
                raise PublicError("filtro_sem_suporte", "Use uma única competência mensal coerente")
            # O mês define o recorte e não a data de execução. Dias são recusados para
            # evitar apresentar linhas de competência como pagamentos daquele intervalo.
            from calendar import monthrange

            if q.data_inicial.day != 1 or q.data_final.day != monthrange(y, m)[1]:
                raise PublicError("filtro_sem_suporte", "Dados PB aceita um mês civil completo ou ano e periodo")
            year, month = y, m
        if not year or (not annual and not month):
            raise PublicError("filtros_obrigatorios", "Informe ano" if annual else "Informe ano e periodo (mês)")
        params = {
            "anoInicioVigencia" if q.operacao == O.CONTRATOS else "ano": year,
            "mes": month,
            "page": q.pagina,
            "per_page": q.limite,
        }
        if company_parameter:
            params[company_parameter] = q.cnpj
        if org_parameter:
            params[org_parameter] = q.cnpj_orgao if org_parameter == "cnpjOrgao" else q.codigo_orgao
        if q.identificador:
            key = {O.CONTRATOS: "numeroContrato", O.LICITACOES: "numeroLicitacao"}.get(q.operacao, "numeroEmpenho")
            params[key] = q.identificador
        try:
            cap = await self.get(f"{BASE}/{route}", params)
        except PublicError as error:
            # Este portal usa 404 tanto em recortes sem registros quanto em rotas ausentes.
            if error.code == "nao_encontrado":
                raise PublicError(
                    "sem_confirmacao", "Dados PB respondeu 404. O recorte não foi confirmado."
                ) from error
            raise
        payload = object_item(cap.json())
        raw = items(payload, "dados")
        pagination = object_item(payload.get("paginacao"))
        pages, total = integer(pagination.get("total_paginas")), integer(pagination.get("total"))
        if pages is None or total is None:
            raise PublicError("schema_fonte", "Dados PB sem metadados de paginação")
        rows = [mapped for item in raw if (mapped := normalize(q.operacao, item, cap.url, year, month))]
        warnings = [WARNINGS[q.operacao]]
        if len(raw) != len(rows):
            warnings.append(f"{len(raw) - len(rows)} registros sem identificador reconhecido")
        return Page(
            cap,
            rows,
            q.pagina + 1 if q.pagina < pages else None,
            total,
            warnings,
            raw_count=len(raw),
            local=["cnpj"] if q.cnpj else [],
        )


def normalize(op: O, entry: dict, source_url: str, year: int, month: int | None) -> Row | None:
    organization = clean_text(entry.get("nomeOrgao") or entry.get("descricaoUnidadeGestora") or entry.get("orgao"))
    org_cnpj = corporate_id(entry.get("cnpjOrgao"))
    company = corporate_id(
        entry.get("cpfCnpjCredor") or entry.get("cpfCnpj") or entry.get("cnpjCpfCredor") or entry.get("cnpjCpf")
    )
    pub = parse_date(entry.get("dataPublicacao"))
    ids = selected(
        entry,
        (
            "numeroEmpenho",
            "numeroDocumento",
            "numeroAp",
            "registroCge",
            "cadastroCge",
            "numeroContrato",
            "numeroProcessoLicitacao",
            "numeroProcesso",
            "numeroLicitacao",
            "codigoReceita",
        ),
    )
    params = selected(
        entry,
        (
            "ano",
            "mes",
            "anoExercicio",
            "anoInicioVigencia",
            "tipoPoder",
            "codigoOrgao",
            "nomeOrgao",
            "codigoUnidade",
            "nomeUnidade",
            "codigoUnidadeGestora",
            "descricaoUnidadeGestora",
            "codigoFuncao",
            "nomeFuncao",
            "codigoNatureza",
            "nomeNatureza",
            "codigoFonte",
            "fonteRecurso",
            "dataEmpenho",
            "dataMovimento",
            "dataInsercao",
            "dataExecucao",
            "status",
            "tipoLiquidacao",
            "dataAbertura",
            "dataInicioVigencia",
            "dataTerminoVigencia",
            "dataPublicacao",
            "modalidade",
            "situacao",
            "valorEmpenhado",
            "valorLiquidado",
            "valorPago",
            "valorAnulado",
            "valorAnuladoLD",
            "valorGD",
            "valorSuplementado",
            "valorOriginal",
            "valorAditivos",
            "valorApostilas",
            "valorTotal",
            "valorEstimado",
            "valorAdjudicado",
            "realizadaNoMes",
            "previstaNoMes",
            "categoriaEconomica",
            "codigoItemDespesa",
            "tipoNotaEmpenho",
            "tipo",
            "descricaoTipo",
        ),
    )
    anchor = next((v for v in ids.values() if v is not None and v != ""), None)
    if anchor is None or not organization and op != O.RECEITAS:
        return None
    if company:
        params.update(cnpj=company, fornecedor=clean_text(entry.get("nomeCredor") or entry.get("contratado")))
    title = organization
    amount_field, nature = {
        O.DESPESAS: (None, None),
        O.EMPENHOS: ("valorEmpenhado", "valor_empenhado_publicado"),
        O.LIQUIDACOES: (None, None),
        O.PAGAMENTOS: ("valorPago", "valor_pago_informado_ordem_cronologica"),
        O.CONTRATOS: ("valorTotal", "valor_total_contrato"),
        O.LICITACOES: ("valorEstimado", "valor_estimado"),
        O.RECEITAS: ("realizadaNoMes", "receita_realizada_no_mes"),
    }[op]
    # A identidade é escopada por entidade e dimensões do registro. Inclui a
    # classificação nos agregados para não colapsar fontes ou rubricas distintas.
    dims = [
        "codigoOrgao",
        "codigoUnidade",
        "codigoUnidadeGestora",
        "codigoNatureza",
        "codigoFonte",
        "fonteRecurso",
        "tipoNotaEmpenho",
        "codigoItemDespesa",
        "tipoLiquidacao",
        "dataMovimento",
        "dataEmpenho",
        "dataExecucao",
    ]
    dataset_id = canonical_digest([year, month, organization, ids, company, *[params.get(k) for k in dims]])
    if op in {O.CONTRATOS, O.LICITACOES}:
        title = clean_text(entry.get("objeto"))
    elif op == O.EMPENHOS and company:
        title = clean_text(entry.get("descricaoEmpenho"))
    elif op == O.RECEITAS:
        title = clean_text(entry.get("tipo"))
    identifiers = {key: str(value) for key, value in ids.items() if value not in ("", None)}
    url = source_url
    if op == O.CONTRATOS and isinstance(entry.get("urlContrato"), str):
        if match := PNCP_LINK.fullmatch(entry["urlContrato"]):
            cnpj_orgao, contract_year, seq = match.groups()
            if pncp_id := reference(f"{cnpj_orgao}-2-{int(seq):06d}/{contract_year}"):
                identifiers["pncp"] = pncp_id
                org_cnpj = org_cnpj or corporate_id(cnpj_orgao)
                url = entry["urlContrato"]
    amount = money(entry.get(amount_field)) if amount_field else None
    if op == O.PAGAMENTOS and not epoch_iso(entry.get("dataExecucao")):
        amount = None
    if op != O.LICITACOES:
        params.update(companhia_confirmada=bool(company))
    native_id = str(anchor) if op == O.CONTRATOS and ids.get("registroCge") else dataset_id
    return Row(
        Record(
            fonte=PB.id,
            conjunto=op.value,
            id_original=native_id,
            tipo=op.value,
            titulo=title or f"Registro {anchor}",
            esfera="E",
            uf="PB",
            cnpj=company,
            cnpj_orgao=org_cnpj,
            orgao=organization,
            valor=amount,
            moeda="BRL" if amount is not None else None,
            natureza_valor=nature,
            data_publicacao=pub,
            competencia=f"{year:04d}-{month:02d}" if month else str(year),
            url_oficial=url,
            identificadores=identifiers,
            atributos=params,
        ),
        {**ids, **params},
    )
