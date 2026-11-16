"""Retira o armazenamento de arquivos da versão 0.1."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EXCLUSIVE_HISTORY = """
DELETE FROM query_history q
WHERE q.request->>'fonte' = 'tce_pb'
   OR (
       q.response->'fontes' @> '[{"fonte":"tce_pb"}]'
       AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(q.response->'fontes') f
           WHERE f->>'fonte' <> 'tce_pb'
       )
   )
"""

# Mantém consultas que também pesquisaram uma API e recalcula os contadores usados no painel.
MIXED_HISTORY = """
WITH affected AS (
    SELECT q.id,
        coalesce((
            SELECT jsonb_agg(f ORDER BY ordinal)
            FROM jsonb_array_elements(q.response->'fontes') WITH ORDINALITY AS entries(f, ordinal)
            WHERE f->>'fonte' <> 'tce_pb'
        ), '[]'::jsonb) AS fontes,
        coalesce((
            SELECT jsonb_agg(r ORDER BY ordinal)
            FROM jsonb_array_elements(q.response->'registros') WITH ORDINALITY AS entries(r, ordinal)
            WHERE r->>'fonte' <> 'tce_pb'
        ), '[]'::jsonb) AS registros
    FROM query_history q
    WHERE q.response->'fontes' @> '[{"fonte":"tce_pb"}]'
       OR q.response->'registros' @> '[{"fonte":"tce_pb"}]'
), counts AS (
    SELECT a.*,
      (SELECT count(*) FROM jsonb_array_elements(a.fontes) f WHERE f->>'estado' IN ('ok', 'vazio', 'incompleto')) AS sources,
      (SELECT count(*) FROM jsonb_array_elements(a.fontes) f WHERE f->'cache' = 'true') AS hits
    FROM affected a
), states AS (
    SELECT c.*, CASE
      WHEN c.sources = 0 THEN 'erro'
      WHEN c.sources < jsonb_array_length(c.fontes) THEN 'parcial'
      WHEN c.fontes @> '[{"estado":"incompleto"}]' THEN 'incompleto'
      WHEN jsonb_array_length(c.registros) > 0 THEN 'ok'
      ELSE 'vazio'
    END AS estado
    FROM counts c
)
UPDATE query_history q
SET request = q.request - 'ordem',
    response = q.response || jsonb_build_object(
        'fontes', a.fontes,
        'registros', a.registros,
        'estado', a.estado,
        'relacoes', coalesce((
            SELECT jsonb_agg(r ORDER BY ordinal)
            FROM jsonb_array_elements(q.response->'relacoes') WITH ORDINALITY AS entries(r, ordinal)
            WHERE coalesce(r->>'chave', '') NOT LIKE 'tce_pb:%'
        ), '[]'::jsonb),
        'divergencias', coalesce((
            SELECT jsonb_agg(d ORDER BY ordinal)
            FROM jsonb_array_elements(q.response->'divergencias') WITH ORDINALITY AS entries(d, ordinal)
            WHERE coalesce(d->>'chave', '') NOT LIKE 'tce_pb:%'
        ), '[]'::jsonb)
    ),
    state = a.estado, sources = a.sources, cache_hits = a.hits
FROM states a
WHERE q.id = a.id
"""


def upgrade():
    op.execute(EXCLUSIVE_HISTORY)
    op.execute(MIXED_HISTORY)
    op.execute("DELETE FROM query_cache WHERE source_id = 'tce_pb'")
    op.execute("DELETE FROM evidence WHERE source_id = 'tce_pb'")
    op.execute("DELETE FROM record_versions WHERE source_id = 'tce_pb'")
    op.execute(
        "DELETE FROM audit_events WHERE action IN ('ingestao_solicitada', 'ingestao_concluida', 'ingestao_falhou') "
        "OR data->>'fonte' = 'tce_pb'"
    )
    op.execute("DELETE FROM sources WHERE id = 'tce_pb'")
    for name in ("jobs", "sagres_active", "sagres_rows", "sagres_archives"):
        op.drop_table(name)


def downgrade():
    raise RuntimeError(
        "A migração 0002 remove os dados do antigo importador. Use um backup para voltar à versão 0.1."
    )
