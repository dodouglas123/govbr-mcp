"""Cliente de diagnóstico autenticado. O token é lido do ambiente."""

import argparse
import asyncio
import json
import os
import sys

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

EXAMPLES = (
    ("gov_consultar_contrato", {"fonte": "pncp", "identificador": "04564530000113-2-000059/2024"}),
    ("gov_pesquisar_licitacoes", {"fonte": "pncp", "uf": "PB", "modalidade": 6, "data_inicial": "2025-09-01",
                                 "data_final": "2025-09-05", "limite": 10}),
    ("gov_consultar_dados_fiscais", {"fonte": "siconfi", "codigo_ibge": 2507507, "ano": 2024,
                                    "anexo": "DCA-Anexo I-D", "limite": 5}),
    ("gov_consultar_municipio", {"codigo_ibge": 2507507}),
    ("gov_consultar_fornecedor", {"fonte": "compras", "cnpj": "00000000000191"}),
    ("gov_consultar_empenhos", {"fonte": "dados_pb", "ano": 2026, "periodo": 7, "limite": 5}),
)


async def call(session, name, args):
    result = await session.call_tool(name, args)
    if result.is_error or not result.structured_content:
        raise RuntimeError(f"{name}: {result.content}")
    return result.structured_content


async def run(streams, selected):
    async with ClientSession(streams[0], streams[1]) as client:
        ready = await client.initialize()
        listing = (await client.list_tools()).tools
        assert len(listing) >= 25 and all(tool.output_schema for tool in listing)
        print(json.dumps({"servidor": ready.server_info.name, "protocolo": ready.protocol_version, "ferramentas": len(listing)}))
        if not selected:
            result = await call(client, "gov_listar_fontes", {})
            assert any(source["id"] == "pncp" for source in result["fontes"])
            return
        examples = list(EXAMPLES)
        for name, filters in examples:
            result = await call(client, name, {"filtros": filters})
            assert result["registros"], (name, result["fontes"])
            row = result["registros"][0]
            ev = await call(client, "gov_obter_evidencias", {"evidencia_id": row["evidencia_id"]})
            assert len(ev["sha256"]) == 64 and ev["url"].startswith("https://") and ev["normalized"]["id_original"] == row["id_original"]
            history = await call(client, "gov_status_consulta", {"consulta_id": result["consulta_id"]})
            assert history["response"]["consulta_id"] == result["consulta_id"]
            print(json.dumps({"ferramenta": name, "fonte": row["fonte"], "registros": len(result["registros"]),
                              "url": ev["request_url"], "sha256": ev["sha256"], "capturado_em": ev["captured_at"],
                              "consulta_id": result["consulta_id"], "id_original": row["id_original"]}, ensure_ascii=False))


async def main(args):
    if args.stdio:
        params = StdioServerParameters(command=sys.executable, args=["-m", "govbr", "stdio"],
                                       env={key: value for key, value in os.environ.items() if key.startswith("GOVBR_")})
        async with stdio_client(params) as streams:
            await run(streams, args.live)
    else:
        token = os.environ.get("GOVBR_TEST_TOKEN")
        if not token:
            raise SystemExit("Defina GOVBR_TEST_TOKEN com uma chave de leitura.")
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, trust_env=False, timeout=65) as http:
            async with streamable_http_client(args.url, http_client=http, terminate_on_close=False) as streams:
                await run(streams, args.live)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8787/mcp")
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--live", action="store_true")
    asyncio.run(main(parser.parse_args()))
