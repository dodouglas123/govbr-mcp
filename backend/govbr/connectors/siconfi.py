from __future__ import annotations

from govbr.catalog import SICONFI
from govbr.connectors.base import Connector, Page, Row, allow, items, object_item, require
from govbr.models import UFS, Operation, PublicError, Query, Record
from govbr.normalize import canonical_digest, clean_text, integer, money, selected

BASE = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt"
DCA_DESPESAS_FUNCAO = "DCA-Anexo I-E"
DCA_RECEITAS = "DCA-Anexo I-C"


class Siconfi(Connector):
    source = SICONFI
    hosts = frozenset({"apidatalake.tesouro.gov.br"})
    interval_seconds = 1.05

    async def health(self):
        cap = await self.get(f"{BASE}/entes", {"limit": 1})
        items(cap.json(), "items")
        return cap

    async def search(self, query: Query, *, page_size: int | None = None) -> Page:
        allow(
            query,
            "ano",
            "ente_fiscal",
            "codigo_ibge",
            "uf",
            "esfera",
            "demonstrativo",
            "anexo",
            "periodo",
            "poder",
            "periodicidade",
        )
        require(query, "ano")
        ente = query.ente_fiscal or query.codigo_ibge or (int(UFS[query.uf]) if query.uf else None)
        if not ente:
            raise PublicError("filtros_obrigatorios", "Informe ente_fiscal, codigo_ibge ou UF do governo estadual")
        if query.uf and (ente >= 10 and not str(ente).startswith(UFS[query.uf]) or ente == 1):
            raise PublicError("identificador_invalido", "Ente fiscal incompatível com a UF")
        classificacao = (
            "M"
            if ente >= 1000000
            else "F"
            if ente == 1
            else "D"
            if ente == 53
            else "E"
            if str(ente) in UFS.values()
            else None
        )
        if classificacao is None:
            raise PublicError("identificador_invalido", "Use 1 para União, o código da UF ou IBGE municipal")
        if query.esfera and query.esfera != classificacao:
            raise PublicError("filtro_sem_suporte", "Esfera incompatível com o ente fiscal informado")
        report = query.demonstrativo or "DCA"
        if query.operacao == Operation.RECEITAS and report != "DCA":
            raise PublicError(
                "filtro_sem_suporte", "Receitas usa DCA-Anexo I-C. Use dados fiscais para outros demonstrativos."
            )
        size = page_size or query.limite
        params = {
            "an_exercicio": query.ano,
            "id_ente": ente,
            "no_anexo": query.anexo or (DCA_RECEITAS if query.operacao == Operation.RECEITAS else None),
            "limit": size,
            "offset": (query.pagina - 1) * size,
        }
        if report == "DCA" and any((query.periodo, query.poder, query.periodicidade)):
            raise PublicError("filtro_sem_suporte", "DCA é anual e não aceita período, poder ou periodicidade")
        if report in {"RREO", "RGF"}:
            require(query, "periodo")
            if query.periodo is None or query.periodo > (6 if report == "RREO" else 3):
                raise PublicError("filtro_sem_suporte", "Período fora do demonstrativo")
            params.update(nr_periodo=query.periodo, co_tipo_demonstrativo=report)
        if report == "RREO" and (query.poder or query.periodicidade):
            raise PublicError("filtro_sem_suporte", "RREO não aceita filtro de poder ou periodicidade")
        if report == "RGF":
            require(query, "poder", "periodicidade")
            if query.periodicidade == "S" and query.periodo == 3:
                raise PublicError("filtro_sem_suporte", "RGF semestral aceita períodos 1 e 2")
            params.update(co_poder=query.poder, in_periodicidade=query.periodicidade)
        cap = await self.get(f"{BASE}/{report.lower()}", params, bytes_limit=4 * 1024 * 1024)
        payload = object_item(cap.json())
        raw = items(payload, "items")
        if not isinstance(payload.get("hasMore"), bool):
            raise PublicError("schema_fonte", "SICONFI não retornou o indicador de paginação")
        rows, missing = [], 0
        for entry in raw:
            code, account = clean_text(entry.get("cod_conta")), clean_text(entry.get("conta"))
            org = clean_text(entry.get("instituicao"))
            annex, column = clean_text(entry.get("anexo")), clean_text(entry.get("coluna"))
            registered_ent = integer(entry.get("cod_ibge"))
            if (
                registered_ent != ente
                or integer(entry.get("exercicio")) != query.ano
                or not (code and account and annex and column)
            ):
                missing += 1
                continue
            label = clean_text(entry.get("rotulo"))
            # A conta pode repetir entre blocos e colunas do mesmo anexo.
            power = clean_text(entry.get("poder") or entry.get("co_poder") or query.poder)
            comp = (
                str(query.ano)
                if report == "DCA"
                else f"{query.ano}/{query.periodo}/{entry.get('periodicidade') or query.periodicidade or 'B'}"
            )
            position = [ente, report, comp, annex, code, account, label, column, power]
            amount = money(entry.get("valor"))
            details = {
                "demonstrativo": report,
                "anexo": annex,
                "rotulo": label,
                "coluna": column,
                "poder": power,
                "codigo_conta": code,
                "ente": ente,
            }
            rows.append(
                Row(
                    Record(
                        fonte=SICONFI.id,
                        conjunto=report.lower(),
                        id_original=canonical_digest(position),
                        tipo="linha_demonstrativo",
                        titulo=account,
                        esfera=classificacao,
                        uf=clean_text(entry.get("uf"), 2),
                        codigo_ibge=ente if ente >= 1000000 else None,
                        orgao=org,
                        valor=amount,
                        moeda="BRL" if amount is not None else None,
                        natureza_valor=column,
                        competencia=comp,
                        url_oficial=cap.url,
                        identificadores={"ente_fiscal": str(ente), "conta_siconfi": code},
                        atributos=details,
                    ),
                    selected(
                        entry,
                        (
                            "exercicio",
                            "demonstrativo",
                            "periodo",
                            "periodicidade",
                            "instituicao",
                            "cod_ibge",
                            "uf",
                            "anexo",
                            "rotulo",
                            "coluna",
                            "cod_conta",
                            "conta",
                            "valor",
                            "esfera",
                            "poder",
                        ),
                    ),
                )
            )
        warnings = ["Linhas, subtotais e estágios contábeis exigem seleção antes de comparar ou somar."]
        if missing:
            warnings.append(f"{missing} linhas sem identificadores fiscais coerentes")
        return Page(
            cap, rows, query.pagina + 1 if payload["hasMore"] else None, warnings=warnings, raw_count=len(raw)
        )
