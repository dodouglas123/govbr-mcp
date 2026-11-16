from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from govbr.catalog import CGU
from govbr.connectors.base import Connector, Page, Row, allow, interval, items, object_item, require
from govbr.models import Operation as O
from govbr.models import PublicError, Query, Record
from govbr.normalize import canonical_digest, clean_text, corporate_id, mapping, money, parse_date, selected
from govbr.transport import SafeHTTP

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
PHASES = {O.EMPENHOS: (1, "empenho"), O.LIQUIDACOES: (2, "liquidacao"), O.PAGAMENTOS: (3, "pagamento")}


class Cgu(Connector):
    source = CGU
    hosts = frozenset({"api.portaldatransparencia.gov.br"})
    interval_seconds = 1.0

    def __init__(self, http: SafeHTTP, key: SecretStr | None):
        super().__init__(http)
        self.key = key

    async def authenticated(self, path: str, params: dict | None = None):
        value = self.key.get_secret_value().strip() if self.key else ""
        if not value:
            raise PublicError("credencial_ausente", "Configure GOVBR_CGU_KEY com a sua chave individual da CGU")
        return await self.get(f"{BASE}/{path}", params, headers={"chave-api-dados": value})

    async def health(self):
        cap = await self.authenticated("licitacoes/modalidades")
        items(cap.json())
        return cap

    async def search(self, query: Query) -> Page:
        if not self.key or not self.key.get_secret_value().strip():
            raise PublicError("credencial_ausente", "Configure GOVBR_CGU_KEY com a sua chave individual da CGU")
        operation = query.operacao
        if operation == O.SANCOES:
            return await self.sanctions(query)
        path, params, pagination, warnings = self.plan(query)
        if pagination and query.limite != 15:
            raise PublicError("filtro_sem_suporte", "A API da CGU tem paginação fixa. Use limite=15.")
        if pagination:
            params["pagina"] = query.pagina
        cap = await self.authenticated(path, params)
        payload = cap.json()
        raw = [] if payload is None else [object_item(payload)] if operation == O.CONTRATO else items(payload)
        next_page = query.pagina + 1 if pagination and len(raw) >= 15 else None
        if not pagination:
            start = (query.pagina - 1) * query.limite
            next_page = query.pagina + 1 if start + query.limite < len(raw) else None
            raw = raw[start : start + query.limite]
        rows = [row for entry in raw if (row := normalize(query, entry, cap.url))]
        if len(rows) != len(raw):
            warnings.append(f"{len(raw) - len(rows)} linhas sem identificador ou estágio verificável")
        local = ["uf"] if query.uf and operation in {O.LICITACOES, *PHASES} else []
        if query.cnpj and operation in {O.CONTRATOS, O.TRANSFERENCIAS, O.CONVENIOS, *PHASES}:
            local.append("cnpj")
        return Page(cap, rows, next_page, warnings=warnings, raw_count=len(raw), local=local)

    def plan(self, q: Query) -> tuple[str, dict[str, Any], bool, list[str]]:
        op = q.operacao
        args: dict[str, Any] = {}
        warning: list[str] = []
        if op == O.CONTRATOS and q.cnpj:
            allow(q, "cnpj", "esfera")
            return (
                "contratos/cpf-cnpj",
                {"cpfCnpj": q.cnpj},
                True,
                ["A pesquisa por fornecedor não expõe filtro de data na API da CGU."],
            )
        if op in {O.CONTRATOS, O.LICITACOES}:
            allow(
                q, "codigo_orgao", "data_inicial", "data_final", "esfera", *("uf",) if op == O.LICITACOES else ()
            )
            require(q, "codigo_orgao")
            if q.data_inicial:
                start, end = interval(q, 366, "%d/%m/%Y")
                args.update(dataInicial=start, dataFinal=end)
            basis = "vigência" if op == O.CONTRATOS else "abertura"
            return op.value, {**args, "codigoOrgao": q.codigo_orgao}, True, [f"Intervalo da CGU por {basis}."]
        if op in {O.CONTRATO, O.ADITIVOS}:
            allow(q, "identificador", "esfera")
            require(q, "identificador")
            if not q.identificador or not q.identificador.isascii() or not q.identificador.isdecimal():
                raise PublicError("identificador_invalido", "A CGU requer o ID numérico do contrato")
            return (
                ("contratos/id" if op == O.CONTRATO else "contratos/termo-aditivo"),
                {"id": q.identificador},
                False,
                [],
            )
        if op in PHASES:
            allow(q, "ano", "cnpj", "codigo_orgao", "data_inicial", "data_final", "esfera", "uf")
            fase, _ = PHASES[op]
            if q.cnpj:
                require(q, "ano")
                if q.data_inicial:
                    raise PublicError("filtro_sem_suporte", "Documentos por favorecido aceitam ano de emissão.")
                return (
                    "despesas/documentos-por-favorecido",
                    dict(
                        codigoPessoa=q.cnpj,
                        fase=fase,
                        ano=q.ano,
                        ug=q.codigo_orgao,
                        ordenacaoResultado=3,
                    ),
                    True,
                    [],
                )
            if q.ano:
                raise PublicError(
                    "filtro_sem_suporte",
                    "Documentos por data requerem data de emissão e unidade gestora opcional.",
                )
            start, _ = interval(q, 1, "%d/%m/%Y")
            return (
                "despesas/documentos",
                dict(fase=fase, unidadeGestora=q.codigo_orgao, dataEmissao=start),
                True,
                [],
            )
        if op == O.DESPESAS:
            allow(q, "ano", "codigo_orgao", "esfera")
            require(q, "ano")
            return (
                "despesas/por-orgao",
                {"ano": q.ano, "orgao": q.codigo_orgao},
                True,
                ["Agregado por órgão, separado por estágio."],
            )
        if op == O.TRANSFERENCIAS:
            allow(q, "data_inicial", "data_final", "cnpj", "uf", "codigo_ibge", "codigo_orgao", "esfera")
            start, end = interval(q, 366, "%m/%Y")
            return (
                "despesas/recursos-recebidos",
                dict(
                    mesAnoInicio=start,
                    mesAnoFim=end,
                    tipoFavorecido="Pessoa Jurídica",
                    codigoFavorecido=q.cnpj,
                    codigoIBGE=q.codigo_ibge,
                    uf=q.uf,
                    orgao=q.codigo_orgao,
                ),
                True,
                ["Recursos recebidos por favorecido, UG e mês. A fonte recebe meses completos."],
            )
        if op == O.CONVENIOS:
            allow(
                q,
                "data_inicial",
                "data_final",
                "cnpj",
                "uf",
                "codigo_ibge",
                "codigo_orgao",
                "identificador",
                "esfera",
            )
            if q.data_inicial:
                start, end = interval(q, 366, "%d/%m/%Y")
                args.update(dataInicial=start, dataFinal=end)
            return (
                "convenios",
                dict(
                    **args,
                    convenente=q.cnpj,
                    codigoIBGE=q.codigo_ibge,
                    uf=q.uf,
                    codigoOrgao=q.codigo_orgao,
                    numero=q.identificador,
                ),
                True,
                warning,
            )
        if op == O.EMENDAS:
            allow(q, "ano", "identificador", "esfera")
            return "emendas", dict(ano=q.ano, codigoEmenda=q.identificador), True, warning
        allow(q, "codigo_orgao", "esfera")
        return "orgaos-siafi", dict(codigo=q.codigo_orgao, descricao=q.texto), True, warning

    async def sanctions(self, q: Query) -> Page:
        allow(q, "cnpj", "identificador", "data_inicial", "data_final", "esfera")
        require(q, "cnpj")
        if q.limite != 15:
            raise PublicError("filtro_sem_suporte", "A CGU tem paginação fixa. Use limite=15.")
        dataset = (q.identificador or "ceis").lower()
        if dataset not in {"ceis", "cnep"}:
            raise PublicError("identificador_invalido", "Use identificador ceis ou cnep. O padrão é ceis.")
        params: dict[str, Any] = {"codigoSancionado": q.cnpj, "pagina": q.pagina}
        if q.data_inicial:
            start, end = interval(q, 366, "%d/%m/%Y")
            params.update(dataInicialSancao=start, dataFinalSancao=end)
        cap = await self.authenticated(dataset, params)
        raw = [] if cap.status == 204 else items(cap.json())
        rows = []
        for entry in raw:
            issuer, company = mapping(entry.get("orgaoSancionador")), mapping(entry.get("sancionado"))
            person = mapping(entry.get("pessoa"))
            identifier = clean_text(entry.get("id"))
            observed = corporate_id(
                company.get("codigoFormatado")
                or company.get("cnpjFormatado")
                or person.get("cnpjFormatado")
                or company.get("cnpj")
            )
            if not identifier or observed != q.cnpj:
                continue
            sanction = mapping(entry.get("tipoSancao"))
            props = selected(
                entry,
                ("dataInicioSancao", "dataFimSancao", "dataPublicacaoSancao", "numeroProcesso", "valorMulta"),
            )
            props.update(
                cnpj=observed,
                sancao=clean_text(sanction.get("descricaoPortal") or sanction.get("descricaoResumida")),
            )
            rows.append(
                Row(
                    Record(
                        fonte=CGU.id,
                        conjunto=dataset,
                        id_original=identifier,
                        tipo="sancao_publicada",
                        titulo=props["sancao"] or dataset.upper(),
                        cnpj=observed,
                        orgao=clean_text(issuer.get("nome")),
                        valor=money(entry.get("valorMulta")),
                        moeda="BRL" if entry.get("valorMulta") is not None else None,
                        natureza_valor="multa_informada" if entry.get("valorMulta") is not None else None,
                        data_publicacao=parse_date(entry.get("dataPublicacaoSancao")),
                        url_oficial=cap.url,
                        atributos=props,
                    ),
                    props,
                )
            )
        return Page(
            cap,
            rows,
            q.pagina + 1 if len(raw) >= 15 else None,
            raw_count=len(raw),
            warnings=[f"{len(raw) - len(rows)} sanções sem CNPJ verificável omitidas"]
            if len(raw) != len(rows)
            else [],
        )


def normalize(q: Query, entry: dict, url: str) -> Row | None:
    op = q.operacao
    organization = mapping(entry.get("orgao"))
    unit = mapping(entry.get("unidadeGestora"))
    supplier = mapping(entry.get("fornecedor") or entry.get("convenente"))
    company = corporate_id(
        supplier.get("cnpjFormatado")
        or supplier.get("cnpj")
        or entry.get("codigoFavorecido")
        or entry.get("codigoPessoa")
    )
    identifier = clean_text(entry.get("id"))
    props: dict[str, Any] = {}
    identifiers: dict[str, str] = {}
    publication = parse_date(entry.get("dataPublicacao"))
    compet = None
    title = clean_text(entry.get("objeto"))
    amount, nature = None, None
    dataset = op.value
    scope = "F"
    territory = clean_text(entry.get("ufFavorecido") or entry.get("siglaUFPessoa"), 2)
    org_name = clean_text(
        organization.get("nome") or unit.get("nome") or entry.get("nomeOrgao") or entry.get("orgao")
    )
    org_cnpj = corporate_id(organization.get("cnpj"))
    if op in {O.CONTRATOS, O.CONTRATO}:
        dataset = "contratos"
        publication = parse_date(entry.get("dataPublicacaoDOU"))
        amount, nature = money(entry.get("valorFinalCompra")), "valor_final_contrato"
        props = selected(
            entry,
            (
                "id",
                "numero",
                "objeto",
                "dataAssinatura",
                "dataPublicacaoDOU",
                "dataInicioVigencia",
                "dataFimVigencia",
                "valorInicialCompra",
                "valorFinalCompra",
                "numeroProcesso",
            ),
        )
        if identifier:
            identifiers["contrato_cgu"] = identifier
    elif op == O.ADITIVOS:
        props = selected(entry, ("numero", "objetoAditivo", "dataPublicacao"))
        if not props.get("numero"):
            return None
        identifier = f"{q.identificador}:{props['numero']}"
        title = clean_text(entry.get("objetoAditivo"))
        identifiers["contrato_cgu"] = str(q.identificador)
    elif op in PHASES:
        identifier = clean_text(entry.get("documento"), 100)
        _, nature = PHASES[op]
        amount, event_date = money(entry.get("valor")), parse_date(entry.get("data"))
        compet = event_date.isoformat() if event_date else None
        title = f"Documento de {nature} {identifier or ''}"
        if identifier:
            identifiers["documento_siafi"] = identifier
        props = selected(
            entry,
            (
                "documento",
                "data",
                "fase",
                "especie",
                "codigoUg",
                "codigoOrgao",
                "funcao",
                "subfuncao",
                "programa",
                "acao",
                "categoria",
                "grupo",
                "elemento",
                "valor",
                "numeroProcesso",
            ),
        )
    elif op == O.DESPESAS:
        props = selected(
            entry,
            (
                "ano",
                "codigoOrgao",
                "orgao",
                "codigoOrgaoSuperior",
                "orgaoSuperior",
                "empenhado",
                "liquidado",
                "pago",
            ),
        )
        identifier = (
            f"{q.ano}:{props.get('codigoOrgaoSuperior', '')}:{props['codigoOrgao']}"
            if props.get("codigoOrgao")
            else None
        )
        compet, title = str(q.ano), org_name
    elif op == O.TRANSFERENCIAS:
        if not company:
            return None
        props = selected(
            entry,
            (
                "anoMes",
                "codigoUG",
                "nomeUG",
                "codigoOrgao",
                "nomeOrgao",
                "municipioPessoa",
                "siglaUFPessoa",
                "valor",
            ),
        )
        if entry.get("anoMes") and entry.get("codigoUG"):
            identifier = canonical_digest([entry.get("anoMes"), company, entry.get("codigoUG")])
        title, compet = clean_text(entry.get("nomePessoa")), clean_text(entry.get("anoMes"))
        amount, nature = money(entry.get("valor")), "recursos_recebidos_por_ug_mes"
    elif op == O.CONVENIOS:
        convenio = mapping(entry.get("dimConvenio"))
        title = clean_text(convenio.get("objeto"))
        amount, nature = money(entry.get("valorLiberado")), "valor_liberado_convenio"
        props = selected(
            entry,
            (
                "dataPublicacao",
                "dataReferencia",
                "dataInicioVigencia",
                "dataFinalVigencia",
                "dataUltimaLiberacao",
                "valor",
                "valorLiberado",
                "valorContrapartida",
                "numeroProcesso",
            ),
        )
        props.update(selected(convenio, ("numero", "codigo")))
    elif op == O.EMENDAS:
        props = selected(
            entry,
            (
                "codigoEmenda",
                "ano",
                "tipoEmenda",
                "nomeAutor",
                "numeroEmenda",
                "localidadeDoGasto",
                "funcao",
                "subfuncao",
                "valorEmpenhado",
                "valorLiquidado",
                "valorPago",
                "valorRestoInscrito",
                "valorRestoPago",
            ),
        )
        identifier, compet = clean_text(entry.get("codigoEmenda")), clean_text(entry.get("ano"))
        title = f"Emenda {identifier or ''}"
    elif op == O.ORGAO:
        props = selected(entry, ("nome", "codigoSIAFI", "sigla", "descricaoPoder"))
        identifier = clean_text(entry.get("codigoSIAFI"))
        title = org_name = clean_text(entry.get("nome"))
        org_cnpj = corporate_id(entry.get("cnpj"))
    elif op == O.LICITACOES:
        licitacao, municipality = mapping(entry.get("licitacao")), mapping(entry.get("municipio"))
        title = clean_text(licitacao.get("objeto"))
        territory = clean_text(municipality.get("siglaUF") or municipality.get("uf"), 2)
        amount, nature = money(entry.get("valor")), "valor_licitacao_cgu"
        props = selected(entry, ("id", "dataAbertura", "dataPublicacao", "dataResultadoCompra", "valor"))
        props.update(selected(licitacao, ("numero", "objeto", "numeroProcesso")))
    if not identifier:
        return None
    if company:
        props.update(
            cnpj=company,
            fornecedor=clean_text(
                supplier.get("nome")
                or supplier.get("razaoSocialReceita")
                or entry.get("nomePessoa")
                or entry.get("nomeFavorecido")
            ),
        )
    return Row(
        Record(
            fonte=CGU.id,
            conjunto=dataset,
            id_original=identifier,
            tipo=PHASES[op][1] if op in PHASES else dataset,
            titulo=title or f"Registro {identifier}",
            esfera=scope,
            uf=territory,
            cnpj=company,
            cnpj_orgao=org_cnpj,
            orgao=org_name,
            valor=amount,
            moeda="BRL" if amount is not None else None,
            natureza_valor=nature,
            data_publicacao=publication,
            competencia=compet,
            url_oficial=url,
            identificadores=identifiers,
            atributos=props,
        ),
        props,
    )
