import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

pytestmark = pytest.mark.postgres


def test_api_only_migration_preserves_api_history(monkeypatch):
    database = os.getenv("GOVBR_TEST_DATABASE_URL")
    if not database:
        pytest.skip("GOVBR_TEST_DATABASE_URL ausente")

    schema = f"migration_{uuid4().hex}"
    test_url = make_url(database).update_query_dict({"options": f"-csearch_path={schema},public"})
    monkeypatch.setenv("GOVBR_DATABASE_URL", test_url.render_as_string(hide_password=False))
    database_engine = create_engine(database, hide_parameters=True)
    test_engine = create_engine(test_url, hide_parameters=True)
    config = Config("alembic.ini")
    with database_engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
        # O search_path também inclui public para resolver os operadores de pg_trgm.
        conn.exec_driver_sql(f"CREATE TABLE {schema}.alembic_version (version_num varchar(32) PRIMARY KEY)")

    api, mixed, imported = uuid4(), uuid4(), uuid4()
    pncp_result = {"fonte": "pncp", "estado": "ok", "cache": True}
    sagres_result = {"fonte": "tce_pb", "estado": "ok", "cache": False}
    try:
        command.upgrade(config, "0001")
        with test_engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO sources (id, metadata) VALUES ('tce_pb', '{}'), ('pncp', '{}')")
            conn.exec_driver_sql(
                "INSERT INTO sagres_archives (id, city, dataset, year, sha256, url, captured_at, rows) "
                "VALUES (gen_random_uuid(), 2507507, 'receitas', 2024, repeat('a', 64), 'https://example.org', now(), 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO sagres_rows (archive_id, row_number, title, search_text, fields) "
                "SELECT id, 1, 'receita de teste', 'receita de teste', '{}' FROM sagres_archives"
            )
            for identifier, filters, sources in (
                (api, {"fonte": "pncp"}, [pncp_result]),
                (mixed, {"ordem": "valor"}, [pncp_result, sagres_result]),
                (imported, {"fonte": "tce_pb"}, [sagres_result]),
            ):
                response = {
                    "fontes": sources,
                    "registros": [{"fonte": source["fonte"]} for source in sources],
                    "estado": "ok",
                }
                conn.execute(
                    text(
                        "INSERT INTO query_history VALUES (:id, 'test', 'receitas', 'ok', "
                        "CAST(:request AS jsonb), CAST(:response AS jsonb), now(), 10, 1, :sources)"
                    ),
                    {
                        "id": identifier,
                        "request": json.dumps(filters),
                        "response": json.dumps(response),
                        "sources": len(sources),
                    },
                )

        command.upgrade(config, "head")
        with test_engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
            assert conn.scalars(text("SELECT id FROM sources")).all() == ["pncp"]
            tables = conn.scalars(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
            ).all()
            assert not {"jobs", "sagres_active", "sagres_rows", "sagres_archives"}.intersection(tables)
            history = {
                row.id: row
                for row in conn.execute(
                    text("SELECT id, request, response, state, sources, cache_hits FROM query_history")
                )
            }
            assert set(history) == {api, mixed}
            assert history[api].request == {"fonte": "pncp"}
            assert history[mixed].request == {}
            assert history[mixed].response["fontes"] == [pncp_result]
            assert history[mixed].response["registros"] == [{"fonte": "pncp"}]
            assert (history[mixed].state, history[mixed].sources, history[mixed].cache_hits) == ("ok", 1, 1)
    finally:
        test_engine.dispose()
        with database_engine.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        database_engine.dispose()
