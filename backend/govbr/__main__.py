from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

import uvicorn
from alembic import command
from alembic.config import Config

from govbr.mcp_server import build_mcp
from govbr.models import Query
from govbr.service import GovService
from govbr.settings import ADMIN, READ, Settings
from govbr.web import create_app


async def maintenance(service: GovService, args):
    try:
        await service.db.seed()
        if args.mode == "key-add":
            response = await service.db.key_add(args.label, [READ, ADMIN] if args.admin else [READ], "local:cli")
            print(json.dumps(response, default=str))
        elif args.mode == "query":
            response = await service.query("local:cli", Query.model_validate_json(args.filtros))
            print(response.model_dump_json(indent=2))
    finally:
        await service.close()


def start_async(coroutine):
    # psycopg requires the selector loop on native Windows.
    factory = asyncio.SelectorEventLoop if os.name == "nt" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        return runner.run(coroutine)


def main():
    parser = argparse.ArgumentParser(prog="python -m govbr")
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("stdio")
    commands.add_parser("migrate")
    server = commands.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    key = commands.add_parser("key-add")
    key.add_argument("label")
    key.add_argument("--admin", action="store_true")
    query = commands.add_parser("query")
    query.add_argument("filtros", help="JSON conforme Query")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    for name in ("httpx", "httpcore", "httpx2", "httpcore2", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if args.mode == "migrate":
        command.upgrade(Config("alembic.ini"), "head")
        return
    settings = Settings()
    if args.mode == "serve":
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(settings), host=args.host, port=args.port, access_log=False, proxy_headers=False
            )
        )
        start_async(server.serve())
        return
    if args.mode == "stdio":

        async def stdio():
            service = GovService(settings)
            try:
                await service.db.ping()
                await service.db.seed()
                await build_mcp(service).run_stdio_async()
            finally:
                await service.close()

        start_async(stdio())
        return
    start_async(maintenance(GovService(settings), args))


if __name__ == "__main__":
    main()
