from __future__ import annotations

from urllib.parse import unquote

from govbr.catalog import PNCP
from govbr.connectors.base import (
    Connector,
    Page,
    Row,
    allow,
    interval,
    items,
    object_item,
    upstream_window,
    window_slice,
)
from govbr.models import Operation as O
from govbr.models import PublicError, Query, Record
from govbr.normalize import (
    clean_text,
    corporate_id,
    epoch_iso,
    integer,
    mapping,
    money,
    parse_date,
    pncp_parts,
    selected,
)

BASE = "https://pncp.gov.br"
READ = f"{BASE}/api/consulta/v1"
API = f"{BASE}/api/pncp/v1"


def reference(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        pncp_parts(value)
    except ValueError:
        return None
    return value.upper()


def _ata_row(row: dict) -> Row | None:
    raw = row.get("numeroControlePncpAta") or row.get("numeroControlePNCPAta") or row.get("numeroControlePNCP")
    original = selected(
        row,
        (
            "numeroAtaRegistroPreco",
            "sequencialAta",
            "dataAssinatura",
            "dataVigenciaInicio",
            "dataVigenciaFim",
            "vigenciaInicio",
            "vigenciaFim",
            "dataPublicacaoPncp",
            "dataAtualizacaoGlobal",
            "cancelado",
            "possibilidadeAdesao",
            "modalidadeNome",
        ),
    )
    parent, separator, suffix = raw.rpartition("-") if isinstance(raw, str) else ("", "", "")
    purchase = reference(parent) if separator else None
    seq = integer(suffix)
    if not purchase or not seq:
        return None
    company, kind, year, number = pncp_parts(purchase)
    if kind != "1":
        return None
    identifier = f"{purchase}-{seq:06d}"
    org, unit = mapping(row.get("orgaoEntidade")), mapping(row.get("unidadeOrgao"))
    scope = org.get("esferaId")
    return Row(
        Record(
            fonte=PNCP.id,
            conjunto="atas",
            id_original=identifier,
            tipo="ata",
            titulo=clean_text(row.get("objetoCompra") or row.get("objetoContratacao"))
            or f"Ata {original.get('numeroAtaRegistroPreco') or identifier}",
            esfera=scope if scope in {"F", "E", "M", "D"} else None,
            uf=clean_text(unit.get("ufSigla"), 2),
            codigo_ibge=integer(unit.get("codigoIbge")),
            cnpj_orgao=company,
            orgao=clean_text(org.get("razaoSocial") or row.get("nomeOrgao")),
            data_publicacao=parse_date(row.get("dataPublicacaoPncp")),
            atualizado_na_fonte=epoch_iso(row.get("dataAtualizacaoGlobal")),
            url_oficial=f"{API}/orgaos/{company}/compras/{year}/{number}/atas/{seq}",
            identificadores={"ata_pncp": identifier, "licitacao_pncp": purchase},
            atributos=original,
        ),
        {**original, "numeroControlePNCP": identifier},
    )


def _pncp_row(operation: O, row: dict) -> Row | None:
    if operation == O.ATAS:
        return _ata_row(row)
    organization, unit = mapping(row.get("orgaoEntidade")), mapping(row.get("unidadeOrgao"))
    identifier = reference(row.get("numeroControlePNCP") or row.get("numeroControlePncp"))
    if not identifier:
        return None
    other = reference(row.get("numeroControlePncpCompra") or row.get("numeroControlePNCPCompra"))
    ids = {"pncp": identifier}
    if other and other != identifier:
        ids["licitacao_pncp"] = other
    for key in ("processo", "numeroContratoEmpenho", "numeroCompra"):
        if value := clean_text(row.get(key), 120):
            ids[key] = value
    field, nature = (
        ("valorGlobal", "valor_global_contrato")
        if operation in (O.CONTRATOS, O.CONTRATO)
        else ("valorTotalHomologado", "valor_total_homologado")
        if row.get("valorTotalHomologado") is not None
        else ("valorTotalEstimado", "valor_total_estimado")
    )
    amount = money(row.get(field))
    cnpj_orgao, kind, year, seq = pncp_parts(identifier)
    path = "contratos" if kind == "2" else "editais"
    original_url = f"{BASE}/app/{path}/{cnpj_orgao}/{year}/{seq}"
    supplier = corporate_id(row.get("niFornecedor"))
    if row.get("tipoPessoa") not in {None, "PJ", "J"}:
        supplier = None
    attributes = selected(
        row,
        (
            "modalidadeNome",
            "situacaoCompraNome",
            "numeroContratoEmpenho",
            "numeroAtaRegistroPreco",
            "dataVigenciaInicio",
            "dataVigenciaFim",
            "dataAssinatura",
            "receita",
        ),
    )
    if supplier and (name := clean_text(row.get("nomeRazaoSocialFornecedor"))):
        attributes["fornecedor"] = name
    original = selected(
        row,
        (
            "numeroControlePNCP",
            "numeroControlePncp",
            "numeroControlePNCPAta",
            "numeroControlePncpAta",
            "numeroControlePncpCompra",
            "objetoContrato",
            "objetoCompra",
            "numeroContratoEmpenho",
            "valorGlobal",
            "valorInicial",
            "valorTotalHomologado",
            "valorTotalEstimado",
            "dataPublicacaoPncp",
            "dataAtualizacao",
            "dataAtualizacaoGlobal",
            "dataAssinatura",
            "dataVigenciaInicio",
            "dataVigenciaFim",
        ),
    )
    original["orgaoEntidade"] = selected(organization, ("cnpj", "razaoSocial", "esferaId"))
    original["unidadeOrgao"] = selected(unit, ("codigoIbge", "ufSigla", "municipioNome", "nomeUnidade"))
    if supplier:
        original["niFornecedor"] = supplier
        original["nomeRazaoSocialFornecedor"] = attributes.get("fornecedor")
    scope = organization.get("esferaId")
    if scope not in {"F", "E", "M", "D"}:
        scope = None
    return Row(
        Record(
            fonte=PNCP.id,
            conjunto=("contratos" if operation == O.CONTRATO else operation.value),
            id_original=identifier,
            tipo={
                O.CONTRATO: "contrato_ou_empenho",
                O.CONTRATOS: "contrato_ou_empenho",
                O.LICITACOES: "contratacao",
                O.ATAS: "ata",
            }[operation],
            titulo=clean_text(row.get("objetoContrato") or row.get("objetoCompra") or row.get("objeto"))
            or identifier,
            esfera=scope,
            uf=clean_text(unit.get("ufSigla"), 2),
            codigo_ibge=integer(unit.get("codigoIbge")),
            cnpj=supplier,
            cnpj_orgao=corporate_id(organization.get("cnpj")),
            orgao=clean_text(organization.get("razaoSocial")),
            valor=amount,
            moeda="BRL" if amount is not None else None,
            natureza_valor=nature if amount is not None else None,
            data_publicacao=parse_date(row.get("dataPublicacaoPncp")),
            atualizado_na_fonte=epoch_iso(row.get("dataAtualizacaoGlobal") or row.get("dataAtualizacao")),
            url_oficial=original_url,
            identificadores=ids,
            atributos=attributes,
        ),
        original,
    )


class Pncp(Connector):
    source = PNCP
    hosts = frozenset({"pncp.gov.br"})

    async def health(self):
        capture = await self.get(f"{READ}/orgaos/15126437000305/compras/2025/2417")
        object_item(capture.json())
        return capture

    async def search(self, query: Query) -> Page:
        if query.operacao in {O.CONTRATO, O.DOCUMENTOS, O.ADITIVOS}:
            return await self.details(query)
        if query.operacao == O.ATAS and query.identificador:
            return await self.details(query)
        if query.operacao == O.LICITACOES:
            allow(query, "data_inicial", "data_final", "uf", "codigo_ibge", "modalidade", "cnpj_orgao", "esfera")
            if query.modalidade is None:
                raise PublicError(
                    "filtros_obrigatorios", "Informe modalidade do PNCP, por exemplo 6 para pregão eletrônico"
                )
        elif query.operacao == O.ATAS:
            allow(query, "data_inicial", "data_final", "cnpj_orgao")
        else:
            allow(query, "data_inicial", "data_final", "uf", "codigo_ibge", "cnpj", "cnpj_orgao", "esfera")
        start, end = interval(query, 90, "%Y%m%d")
        page, size, shift = upstream_window(query)
        params = {"dataInicial": start, "dataFinal": end, "pagina": page, "tamanhoPagina": size}
        path = query.operacao.value
        local = []
        if query.operacao == O.LICITACOES:
            path = "contratacoes/publicacao"
            params.update(
                codigoModalidadeContratacao=query.modalidade,
                uf=query.uf,
                codigoMunicipioIbge=query.codigo_ibge,
                cnpj=query.cnpj_orgao,
            )
            local = ["esfera"] if query.esfera else []
        elif query.operacao == O.CONTRATOS:
            params["cnpjOrgao"] = query.cnpj_orgao
            local = [
                field for field in ("uf", "codigo_ibge", "cnpj", "esfera") if getattr(query, field) is not None
            ]
        else:
            params["cnpj"] = query.cnpj_orgao
        cap = await self.get(f"{READ}/{path}", params)
        if cap.status == 204:
            return Page(cap, [], total=0, local=local)
        envelope = object_item(cap.json())
        raw = items(envelope, "data")
        pages, total = integer(envelope.get("totalPaginas")), integer(envelope.get("totalRegistros"))
        if pages is None or total is None:
            raise PublicError("schema_fonte", "PNCP sem metadados de paginação")
        raw, next_page = window_slice(query, raw, shift, page < pages)
        rows = [mapped for row in raw if (mapped := _pncp_row(query.operacao, row)) is not None]
        warnings = (
            [f"{len(raw) - len(rows)} registros PNCP sem identificador reconhecido"]
            if len(raw) != len(rows)
            else []
        )
        if local:
            warnings.append(
                "Filtros locais aplicados à página do PNCP. Uma página vazia ainda pode ter continuação."
            )
        if query.operacao == O.ATAS:
            warnings.append("O intervalo de atas representa vigência na API do PNCP.")
        return Page(cap, rows, next_page, total, warnings, len(raw), local)

    async def details(self, query: Query) -> Page:
        allow(query, "identificador")
        if not query.identificador:
            raise PublicError("filtros_obrigatorios", "Informe o identificador PNCP")
        try:
            company, kind, year, sequence = pncp_parts(query.identificador)
        except ValueError as error:
            raise PublicError("identificador_invalido", str(error)) from error
        path = "contratos" if kind == "2" else "compras"
        parent_id = f"{company}-{kind}-{sequence:06d}/{year}"
        path = f"{API}/orgaos/{company}/{path}/{year}/{sequence}"
        if query.operacao == O.CONTRATO:
            if kind != "2":
                raise PublicError(
                    "identificador_invalido", "A consulta de contrato requer um controle PNCP do tipo 2"
                )
            cap = await self.get(path)
            row = _pncp_row(query.operacao, object_item(cap.json()))
            if row is None:
                raise PublicError("schema_fonte", "Contrato PNCP sem identificador reconhecido")
            return Page(cap, [row] if query.pagina == 1 else [], total=1)
        if query.operacao == O.ATAS:
            if kind != "1":
                raise PublicError(
                    "identificador_invalido", "Atas por contratação requerem controle PNCP do tipo 1"
                )
            index, size, shift = upstream_window(query)
            cap = await self.get(path + "/atas", {"pagina": index, "tamanhoPagina": size})
            if cap.status == 204:
                return Page(cap, [], total=0)
            envelope = object_item(cap.json())
            pages, total = integer(envelope.get("totalPaginas")), integer(envelope.get("totalRegistros"))
            if pages is None or total is None:
                raise PublicError("schema_fonte", "PNCP sem metadados de paginação da ata")
            batch, next_page = window_slice(query, items(envelope, "data"), shift, index < pages)
            rows = [mapped for item in batch if (mapped := _ata_row(item))]
            return Page(
                cap,
                rows,
                next_page,
                total,
                warnings=["Atas vinculadas pela contratação informada."],
                raw_count=len(batch),
            )
        is_document = query.operacao == O.DOCUMENTOS
        if not is_document and kind != "2":
            raise PublicError("identificador_invalido", "Termos requerem um controle PNCP do tipo 2")
        cap = await self.get(path + ("/arquivos" if is_document else "/termos"))
        raw = items(cap.json()) if cap.status != 204 else []
        start = (query.pagina - 1) * query.limite
        rows: list[Row] = []
        for entry in raw[start : start + query.limite]:
            seq = integer(
                entry.get("sequencialDocumento") if is_document else entry.get("sequencialTermoContrato")
            )
            if not seq:
                seq = integer(entry.get("sequencialTermo"))
            if not seq:
                continue
            original_url = f"{path}/arquivos/{seq}" if is_document else cap.url
            title = unquote(
                str(
                    entry.get("titulo")
                    or entry.get("objetoTermoContrato")
                    or entry.get("numeroTermoContrato")
                    or f"Termo {seq}"
                )
            )
            original = selected(
                entry,
                (
                    "titulo",
                    "tipoDocumentoNome",
                    "dataPublicacaoPncp",
                    "sequencialDocumento",
                    "numeroTermoContrato",
                    "objetoTermoContrato",
                    "valorGlobal",
                    "valorAcrescido",
                    "tipoTermoContratoNome",
                ),
            )
            rows.append(
                Row(
                    Record(
                        fonte=PNCP.id,
                        conjunto=query.operacao.value,
                        id_original=f"{parent_id}:{seq}",
                        tipo="documento" if is_document else "termo_contrato",
                        titulo=clean_text(title) or f"Registro {seq}",
                        cnpj_orgao=company,
                        data_publicacao=parse_date(entry.get("dataPublicacaoPncp")),
                        url_oficial=original_url,
                        identificadores={"registro_pncp": parent_id},
                        atributos={
                            "tipo_documento": clean_text(entry.get("tipoDocumentoNome")),
                            "conteudo": "documento externo tratado como dado não confiável",
                        }
                        if is_document
                        else selected(entry, ("tipoTermoContratoNome", "valorAcrescido", "dataAssinatura")),
                    ),
                    original,
                )
            )
        expected = len(raw[start : start + query.limite])
        warnings = [f"{expected - len(rows)} registros sem sequência verificável"] if expected != len(rows) else []
        return Page(
            cap, rows, query.pagina + 1 if start + query.limite < len(raw) else None, len(raw), warnings, expected
        )
