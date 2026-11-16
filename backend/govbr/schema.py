from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
ts = DateTime(timezone=True)

sources = Table(
    "sources",
    metadata,
    Column("id", String(50), primary_key=True),
    Column("metadata", JSONB, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("ttl_override", Integer),
    Column("last_ok", ts),
    Column("last_error_at", ts),
    Column("last_error", String(50)),
    Column("last_latency_ms", Integer),
)
evidence = Table(
    "evidence",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("source_id", ForeignKey("sources.id"), nullable=False),
    Column("dataset", String(60), nullable=False),
    Column("upstream_id", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("request_url", Text, nullable=False),
    Column("captured_at", ts, nullable=False),
    Column("stored_at", ts, nullable=False, server_default=func.now()),
    Column("sha256", String(64), nullable=False),
    Column("filters", JSONB, nullable=False),
    Column("original", JSONB, nullable=False),
    Column("normalized", JSONB, nullable=False),
    Column("transforms", JSONB, nullable=False),
    Column("limitations", JSONB, nullable=False),
)
Index("evidence_storage_idx", evidence.c.stored_at)
versions = Table(
    "record_versions",
    metadata,
    Column("source_id", ForeignKey("sources.id"), primary_key=True),
    Column("dataset", String(60), primary_key=True),
    Column("upstream_id", Text, primary_key=True),
    Column("sha256", String(64), primary_key=True),
    Column("record_type", String(60), nullable=False),
    Column("cnpj", String(14)),
    Column("ibge", Integer),
    Column("title", Text, nullable=False),
    Column("identifiers", JSONB, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("first_seen", ts, nullable=False),
    Column("last_seen", ts, nullable=False),
)
Index("version_cnpj_idx", versions.c.cnpj, versions.c.dataset)
Index("version_ibge_idx", versions.c.ibge, versions.c.dataset)
Index("version_recent_idx", versions.c.last_seen)
Index("version_id_gin_idx", versions.c.identifiers, postgresql_using="gin")
Index(
    "version_fts_idx", func.to_tsvector(text("'portuguese'::regconfig"), versions.c.title), postgresql_using="gin"
)
Index("version_title_trgm_idx", versions.c.title, postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"})
docs = Table(
    "documents",
    metadata,
    Column("evidence_id", ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True),
    Column("sha256", String(64), primary_key=True),
    Column("content", LargeBinary, nullable=False),
    Column("downloaded_at", ts, nullable=False),
)
cache = Table(
    "query_cache",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("source_id", ForeignKey("sources.id"), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("expires_at", ts, nullable=False),
)
Index("cache_expiry_idx", cache.c.expires_at)
history = Table(
    "query_history",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("operation", String(50), nullable=False),
    Column("state", String(32), nullable=False),
    Column("request", JSONB, nullable=False),
    Column("response", JSONB, nullable=False),
    Column("created_at", ts, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("cache_hits", Integer, nullable=False),
    Column("sources", Integer, nullable=False),
)
Index("history_actor_idx", history.c.actor, history.c.created_at.desc())
Index("history_time_idx", history.c.created_at)
tokens = Table(
    "access_tokens",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("label", String(100), nullable=False),
    Column("digest", String(64), nullable=False, unique=True),
    Column("scopes", JSONB, nullable=False),
    Column("created_at", ts, nullable=False),
    Column("revoked_at", ts),
)
rate = Table(
    "rate_limits",
    metadata,
    Column("actor", String(100), primary_key=True),
    Column("minute", BigInteger, primary_key=True),
    Column("count", Integer, nullable=False),
)
Index("rate_minute_idx", rate.c.minute)
audit = Table(
    "audit_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("action", String(50), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("created_at", ts, nullable=False),
)
Index("audit_time_idx", audit.c.created_at)
investigations = Table(
    "investigations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("title", String(160), nullable=False),
    Column("notes", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("updated_at", ts, nullable=False),
)
Index("investigation_actor_idx", investigations.c.actor, investigations.c.updated_at.desc())
investigation_queries = Table(
    "investigation_queries",
    metadata,
    Column("investigation_id", ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True),
    Column("query_id", ForeignKey("query_history.id", ondelete="CASCADE"), primary_key=True),
)
