from govbr.catalog import IBGE_SOURCE
from govbr.connectors.base import Connector, Page, Row, allow, items, object_item
from govbr.models import UFS, PublicError, Query, Record
from govbr.normalize import clean_text, integer, mapping, search_key, selected

BASE = "https://servicodados.ibge.gov.br/api/v1/localidades"
UF_BY_CODE = {int(value): name for name, value in UFS.items()}


class Ibge(Connector):
    source = IBGE_SOURCE
    hosts = frozenset({"servicodados.ibge.gov.br"})

    async def health(self):
        cap = await self.get(f"{BASE}/municipios/2507507")
        if object_item(cap.json()).get("id") != 2507507:
            raise PublicError("schema_fonte", "Código territorial inesperado")
        return cap

    async def search(self, query: Query) -> Page:
        allow(query, "codigo_ibge", "uf", "esfera")
        if (
            query.valor_minimo is not None
            or query.valor_maximo is not None
            or query.esfera not in {None, "M", "D"}
        ):
            raise PublicError("filtro_sem_suporte", "Localidades aceita código IBGE, UF e texto")
        if not query.codigo_ibge and not query.uf:
            raise PublicError("filtros_obrigatorios", "Informe UF ou codigo_ibge")
        path = f"municipios/{query.codigo_ibge}" if query.codigo_ibge else f"estados/{query.uf}/municipios"
        cap = await self.get(f"{BASE}/{path}", bytes_limit=5 * 1024 * 1024)
        payload = cap.json()
        if query.codigo_ibge:
            raw = [object_item(payload)] if payload is not None else []
        else:
            raw = items(payload)
        rows = []
        for entry in raw:
            identifier, name = integer(entry.get("id")), clean_text(entry.get("nome"))
            if not identifier or not name:
                continue
            if query.texto and search_key(query.texto) not in search_key(name):
                continue
            uf = UF_BY_CODE.get(identifier // 100000)
            linked_sources = ["pncp", "siconfi"]
            region = mapping(entry.get("regiao-imediata"))
            rows.append(
                Row(
                    Record(
                        fonte=IBGE_SOURCE.id,
                        conjunto="municipios",
                        id_original=str(identifier),
                        tipo="municipio",
                        titulo=name,
                        esfera="D" if uf == "DF" else "M",
                        uf=uf,
                        codigo_ibge=identifier,
                        url_oficial=f"{BASE}/municipios/{identifier}",
                        identificadores={"ibge": str(identifier)},
                        atributos={
                            "fontes_potenciais": linked_sources,
                            "regiao_imediata": clean_text(region.get("nome")),
                        },
                    ),
                    selected(entry, ("id", "nome")),
                )
            )
        start, end = (query.pagina - 1) * query.limite, query.pagina * query.limite
        return Page(
            cap,
            rows[start:end],
            query.pagina + 1 if end < len(rows) else None,
            len(raw),
            raw_count=len(raw),
            local=["texto"] if query.texto else [],
        )
