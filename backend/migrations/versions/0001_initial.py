"""Catálogo, versões, evidências, autenticação, histórico e fila SAGRES."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = (
    """
    CREATE EXTENSION IF NOT EXISTS pg_trgm
    """,
    """
    CREATE TABLE access_tokens (
    id UUID NOT NULL,
    label VARCHAR(100) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    scopes JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (digest)
    )
    """,
    """
    CREATE TABLE audit_events (
    id UUID NOT NULL,
    actor VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX audit_time_idx ON audit_events (created_at)
    """,
    """
    CREATE TABLE investigations (
    id UUID NOT NULL,
    actor VARCHAR(100) NOT NULL,
    title VARCHAR(160) NOT NULL,
    notes TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX investigation_actor_idx ON investigations (actor, updated_at DESC)
    """,
    """
    CREATE TABLE jobs (
    id UUID NOT NULL,
    key VARCHAR(100) NOT NULL,
    actor VARCHAR(100) NOT NULL,
    config JSONB NOT NULL,
    status VARCHAR(24) NOT NULL,
    attempt INTEGER NOT NULL,
    checkpoint INTEGER NOT NULL,
    archive_id UUID,
    next_run TIMESTAMP WITH TIME ZONE,
    lease_until TIMESTAMP WITH TIME ZONE,
    lease_id UUID,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_success_at TIMESTAMP WITH TIME ZONE,
    error VARCHAR(70),
    error_detail TEXT,
    PRIMARY KEY (id),
    UNIQUE (key)
    )
    """,
    """
    CREATE INDEX jobs_due_idx ON jobs (status, next_run)
    """,
    """
    CREATE TABLE query_history (
    id UUID NOT NULL,
    actor VARCHAR(100) NOT NULL,
    operation VARCHAR(50) NOT NULL,
    state VARCHAR(32) NOT NULL,
    request JSONB NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_ms INTEGER NOT NULL,
    cache_hits INTEGER NOT NULL,
    sources INTEGER NOT NULL,
    PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX history_actor_idx ON query_history (actor, created_at DESC)
    """,
    """
    CREATE INDEX history_time_idx ON query_history (created_at)
    """,
    """
    CREATE TABLE rate_limits (
    actor VARCHAR(100) NOT NULL,
    minute BIGINT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (actor, minute)
    )
    """,
    """
    CREATE INDEX rate_minute_idx ON rate_limits (minute)
    """,
    """
    CREATE TABLE sagres_archives (
    id UUID NOT NULL,
    city INTEGER NOT NULL,
    dataset VARCHAR(20) NOT NULL,
    year INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    url TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    complete_at TIMESTAMP WITH TIME ZONE,
    rows INTEGER,
    PRIMARY KEY (id)
    )
    """,
    """
    CREATE UNIQUE INDEX sagres_archives_partition_idx ON sagres_archives (city, dataset, year, sha256)
    """,
    """
    CREATE TABLE sources (
    id VARCHAR(50) NOT NULL,
    metadata JSONB NOT NULL,
    enabled BOOLEAN DEFAULT 'true' NOT NULL,
    ttl_override INTEGER,
    last_ok TIMESTAMP WITH TIME ZONE,
    last_error_at TIMESTAMP WITH TIME ZONE,
    last_error VARCHAR(50),
    last_latency_ms INTEGER,
    PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE evidence (
    id UUID NOT NULL,
    source_id VARCHAR(50) NOT NULL,
    dataset VARCHAR(60) NOT NULL,
    upstream_id TEXT NOT NULL,
    url TEXT NOT NULL,
    request_url TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    stored_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    filters JSONB NOT NULL,
    original JSONB NOT NULL,
    normalized JSONB NOT NULL,
    transforms JSONB NOT NULL,
    limitations JSONB NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(source_id) REFERENCES sources (id)
    )
    """,
    """
    CREATE INDEX evidence_storage_idx ON evidence (stored_at)
    """,
    """
    CREATE TABLE investigation_queries (
    investigation_id UUID NOT NULL,
    query_id UUID NOT NULL,
    PRIMARY KEY (investigation_id, query_id),
    FOREIGN KEY(investigation_id) REFERENCES investigations (id) ON DELETE CASCADE,
    FOREIGN KEY(query_id) REFERENCES query_history (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE query_cache (
    key VARCHAR(64) NOT NULL,
    source_id VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (key),
    FOREIGN KEY(source_id) REFERENCES sources (id)
    )
    """,
    """
    CREATE INDEX cache_expiry_idx ON query_cache (expires_at)
    """,
    """
    CREATE TABLE record_versions (
    source_id VARCHAR(50) NOT NULL,
    dataset VARCHAR(60) NOT NULL,
    upstream_id TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    record_type VARCHAR(60) NOT NULL,
    cnpj VARCHAR(14),
    ibge INTEGER,
    title TEXT NOT NULL,
    identifiers JSONB NOT NULL,
    payload JSONB NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (source_id, dataset, upstream_id, sha256),
    FOREIGN KEY(source_id) REFERENCES sources (id)
    )
    """,
    """
    CREATE INDEX version_cnpj_idx ON record_versions (cnpj, dataset)
    """,
    """
    CREATE INDEX version_fts_idx ON record_versions USING gin (to_tsvector('portuguese'::regconfig, title))
    """,
    """
    CREATE INDEX version_ibge_idx ON record_versions (ibge, dataset)
    """,
    """
    CREATE INDEX version_id_gin_idx ON record_versions USING gin (identifiers)
    """,
    """
    CREATE INDEX version_recent_idx ON record_versions (last_seen)
    """,
    """
    CREATE INDEX version_title_trgm_idx ON record_versions USING gin (title gin_trgm_ops)
    """,
    """
    CREATE TABLE sagres_active (
    city INTEGER NOT NULL,
    dataset VARCHAR(20) NOT NULL,
    year INTEGER NOT NULL,
    archive_id UUID NOT NULL,
    PRIMARY KEY (city, dataset, year),
    FOREIGN KEY(archive_id) REFERENCES sagres_archives (id)
    )
    """,
    """
    CREATE TABLE sagres_rows (
    archive_id UUID NOT NULL,
    row_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    company VARCHAR(14),
    org TEXT,
    org_code VARCHAR(40),
    reference_date DATE,
    search_text TEXT NOT NULL,
    fields JSONB NOT NULL,
    PRIMARY KEY (archive_id, row_number),
    FOREIGN KEY(archive_id) REFERENCES sagres_archives (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX sagres_company_idx ON sagres_rows (archive_id, company)
    """,
    """
    CREATE INDEX sagres_org_idx ON sagres_rows (archive_id, org_code)
    """,
    """
    CREATE INDEX sagres_text_trgm_idx ON sagres_rows USING gin (search_text gin_trgm_ops)
    """,
    """
    CREATE TABLE documents (
    evidence_id UUID NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    content BYTEA NOT NULL,
    downloaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (evidence_id, sha256),
    FOREIGN KEY(evidence_id) REFERENCES evidence (id) ON DELETE CASCADE
    )
    """,
)

def upgrade():
    for statement in SCHEMA:
        op.execute(statement)

def downgrade():
    op.drop_table("documents")
    op.drop_table("sagres_rows")
    op.drop_table("sagres_active")
    op.drop_table("record_versions")
    op.drop_table("query_cache")
    op.drop_table("investigation_queries")
    op.drop_table("evidence")
    op.drop_table("sources")
    op.drop_table("sagres_archives")
    op.drop_table("rate_limits")
    op.drop_table("query_history")
    op.drop_table("jobs")
    op.drop_table("investigations")
    op.drop_table("audit_events")
    op.drop_table("access_tokens")
