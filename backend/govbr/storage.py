from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import Integer, case, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.ext.asyncio import create_async_engine

from govbr import schema as s
from govbr.catalog import ALL_SOURCES
from govbr.models import PublicError, Query, Response, utcnow
from govbr.normalize import canonical_digest
from govbr.settings import Settings


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=3,
            pool_timeout=6,
            hide_parameters=True,
        )

    async def close(self):
        await self.engine.dispose()

    async def ping(self):
        async with self.engine.connect() as connection:
            return (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()

    async def seed(self):
        async with self.engine.begin() as db:
            values = [
                {"id": src.id, "metadata": asdict(src), "enabled": bool(src.capacidades)} for src in ALL_SOURCES
            ]
            statement = upsert(s.sources).values(values)
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[s.sources.c.id],
                    set_={"metadata": statement.excluded.metadata},
                )
            )

    async def source_list(self):
        async with self.engine.connect() as db:
            entries = (await db.execute(select(s.sources).order_by(s.sources.c.id))).mappings()
            return [dict(entry) for entry in entries]

    async def source_report(self, source: str, latency: int, error: str | None = None):
        when = utcnow()
        patch = {"last_latency_ms": latency}
        if error:
            patch.update(last_error_at=when, last_error=error)
        else:
            patch["last_ok"] = when
        async with self.engine.begin() as db:
            await db.execute(update(s.sources).where(s.sources.c.id == source).values(**patch))

    async def source_config(self, source: str, enabled: bool, ttl: int | None, actor: str):
        async with self.engine.begin() as db:
            await db.execute(
                update(s.sources).where(s.sources.c.id == source).values(enabled=enabled, ttl_override=ttl)
            )
            await db.execute(delete(s.cache).where(s.cache.c.source_id == source))
            await self._audit(db, actor, "fonte_atualizada", {"fonte": source, "enabled": enabled, "ttl": ttl})

    async def cache_get(self, key: str):
        async with self.engine.connect() as db:
            return (
                await db.execute(
                    select(s.cache.c.payload).where(
                        s.cache.c.key == key,
                        s.cache.c.expires_at > utcnow(),
                    )
                )
            ).scalar_one_or_none()

    async def write_page(self, query: Query, result, rows, *, sha256: str, ttl: int, key: str | None):
        captured = result.consultado_em
        source = result.fonte
        ev_rows = []
        version_rows = {}
        for row in rows:
            ev_id = uuid4()
            row.record.evidencia_id = ev_id
            normalized = row.record.model_dump(mode="json", exclude={"evidencia_id"})
            ev_rows.append(
                {
                    "id": ev_id,
                    "source_id": source,
                    "dataset": row.record.conjunto,
                    "upstream_id": row.record.id_original,
                    "url": row.record.url_oficial,
                    "request_url": result.url_consulta,
                    "captured_at": captured,
                    "sha256": sha256,
                    "filters": query.filtros(),
                    "original": row.original,
                    "normalized": normalized,
                    "transforms": [
                        "Extrato com campos permitidos e texto sanitizado",
                        "Valor decimal e natureza mantidos separadamente",
                    ],
                    "limitations": result.avisos,
                }
            )
            stable_record = {k: v for k, v in normalized.items() if k != "url_oficial"}
            version_hash = canonical_digest([row.original, stable_record])
            identity = (source, row.record.conjunto, row.record.id_original, version_hash)
            version_rows[identity] = {
                "source_id": source,
                "dataset": row.record.conjunto,
                "upstream_id": row.record.id_original,
                "sha256": version_hash,
                "record_type": row.record.tipo,
                "cnpj": row.record.cnpj,
                "ibge": row.record.codigo_ibge,
                "title": row.record.titulo,
                "identifiers": row.record.identificadores,
                "payload": normalized,
                "first_seen": captured,
                "last_seen": captured,
            }
        async with self.engine.begin() as db:
            if ev_rows:
                await db.execute(insert(s.evidence), ev_rows)
                statement = upsert(s.versions).values([version_rows[i] for i in sorted(version_rows)])
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            s.versions.c[name] for name in ("source_id", "dataset", "upstream_id", "sha256")
                        ],
                        set_={"last_seen": func.greatest(s.versions.c.last_seen, statement.excluded.last_seen)},
                    )
                )
            if key and ttl > 0:
                payload = {
                    "result": result.model_dump(mode="json"),
                    "records": [r.record.model_dump(mode="json") for r in rows],
                }
                statement = upsert(s.cache).values(
                    key=key, source_id=source, payload=payload, expires_at=utcnow() + timedelta(seconds=ttl)
                )
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[s.cache.c.key],
                        set_={"payload": payload, "expires_at": statement.excluded.expires_at},
                    )
                )

    async def evidence_detail(self, id_: UUID):
        async with self.engine.connect() as db:
            evidence = (
                (await db.execute(select(s.evidence).where(s.evidence.c.id == id_))).mappings().one_or_none()
            )
            if not evidence:
                raise PublicError("evidencia_inexistente", "Evidência inexistente ou expirada")
            files = (
                await db.execute(
                    select(s.docs.c.sha256, s.docs.c.downloaded_at)
                    .where(
                        s.docs.c.evidence_id == id_,
                    )
                    .order_by(s.docs.c.downloaded_at.desc())
                )
            ).mappings()
            return {**evidence, "documentos": [dict(row) for row in files]}

    async def document(self, evidence_id: UUID, sha: str | None = None):
        stmt = select(s.docs).where(s.docs.c.evidence_id == evidence_id)
        if sha:
            stmt = stmt.where(s.docs.c.sha256 == sha)
        stmt = stmt.order_by(s.docs.c.downloaded_at.desc()).limit(1)
        async with self.engine.connect() as db:
            row = (await db.execute(stmt)).mappings().one_or_none()
            return dict(row) if row else None

    async def save_document(self, evidence_id: UUID, sha: str, content: bytes):
        async with self.engine.begin() as db:
            await db.execute(
                upsert(s.docs)
                .values(
                    evidence_id=evidence_id,
                    sha256=sha,
                    content=content,
                    downloaded_at=utcnow(),
                )
                .on_conflict_do_nothing()
            )

    async def record_query(self, actor: str, q: Query | dict, report: Response, elapsed_ms: int):
        async with self.engine.begin() as db:
            await db.execute(
                insert(s.history).values(
                    id=report.consulta_id,
                    actor=actor,
                    operation=report.operacao,
                    state=report.estado,
                    request=q if isinstance(q, dict) else q.model_dump(mode="json", exclude_none=True),
                    response=report.model_dump(mode="json"),
                    created_at=report.consultado_em,
                    duration_ms=elapsed_ms,
                    cache_hits=sum(result.cache for result in report.fontes),
                    sources=sum(result.estado in {"ok", "vazio", "incompleto"} for result in report.fontes),
                )
            )

    async def history_list(self, actor: str, offset: int = 0, limit: int = 20):
        columns = [col for col in s.history.columns if col.name not in {"actor", "response"}]
        async with self.engine.connect() as db:
            rows = (
                await db.execute(
                    select(*columns)
                    .where(
                        s.history.c.actor == actor,
                    )
                    .order_by(s.history.c.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def query_detail(self, actor: str, id_: UUID):
        async with self.engine.connect() as db:
            row = (
                (await db.execute(select(s.history).where(s.history.c.actor == actor, s.history.c.id == id_)))
                .mappings()
                .one_or_none()
            )
            if not row:
                raise PublicError("consulta_inexistente", "Consulta inexistente, expirada ou de outro usuário")
            return {k: v for k, v in row.items() if k != "actor"}

    async def stats(self, actor: str):
        async with self.engine.connect() as db:
            queries = (
                (
                    await db.execute(
                        select(
                            func.count().label("consultas"),
                            func.avg(s.history.c.duration_ms).cast(Integer).label("latencia_media_ms"),
                            func.coalesce(func.sum(s.history.c.cache_hits), 0).label("acertos"),
                            func.coalesce(func.sum(s.history.c.sources), 0).label("fontes_consultadas"),
                            func.coalesce(
                                func.sum(case((s.history.c.state.in_(["erro", "parcial"]), 1), else_=0)), 0
                            ).label("erros"),
                        ).where(s.history.c.actor == actor)
                    )
                )
                .mappings()
                .one()
            )
            size = (await db.execute(select(func.pg_database_size(func.current_database())))).scalar_one()
            return {**queries, "banco_bytes": size, "limite_req_min": self.settings.requests_per_minute}

    async def throttle(self, actor: str) -> bool:
        minute = int(utcnow().timestamp()) // 60
        statement = upsert(s.rate).values(actor=actor, minute=minute, count=1)
        async with self.engine.begin() as db:
            count = (
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[s.rate.c.actor, s.rate.c.minute],
                        set_={"count": s.rate.c.count + 1},
                        where=s.rate.c.count < self.settings.requests_per_minute,
                    ).returning(s.rate.c.count)
                )
            ).scalar_one_or_none()
            return count is not None

    async def key_add(self, label: str, scopes: list[str], actor: str):
        token = "govbr_" + secrets.token_urlsafe(36)
        id_ = uuid4()
        async with self.engine.begin() as db:
            await db.execute(
                insert(s.tokens).values(
                    id=id_,
                    label=label,
                    digest=token_digest(token),
                    scopes=scopes,
                    created_at=utcnow(),
                )
            )
            await self._audit(db, actor, "chave_criada", {"id": str(id_), "scopes": scopes})
        return {"id": id_, "token": token, "scopes": scopes}

    async def key_read(self, token: str):
        async with self.engine.connect() as db:
            row = (
                (
                    await db.execute(
                        select(s.tokens.c.id, s.tokens.c.scopes).where(
                            s.tokens.c.digest == token_digest(token),
                            s.tokens.c.revoked_at.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row else None

    async def key_list(self):
        async with self.engine.connect() as db:
            rows = (
                await db.execute(
                    select(
                        s.tokens.c.id,
                        s.tokens.c.label,
                        s.tokens.c.scopes,
                        s.tokens.c.created_at,
                        s.tokens.c.revoked_at,
                    )
                    .order_by(s.tokens.c.created_at.desc())
                    .limit(200)
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def key_revoke(self, id_: UUID, actor: str):
        async with self.engine.begin() as db:
            updated = (
                await db.execute(
                    update(s.tokens)
                    .where(
                        s.tokens.c.id == id_,
                        s.tokens.c.revoked_at.is_(None),
                    )
                    .values(revoked_at=utcnow())
                    .returning(s.tokens.c.id)
                )
            ).scalar_one_or_none()
            if not updated:
                raise PublicError("chave_inexistente", "Chave inexistente ou revogada")
            await self._audit(db, actor, "chave_revogada", {"id": str(id_)})

    async def _audit(self, db, actor: str, action: str, data: dict):
        await db.execute(
            insert(s.audit).values(id=uuid4(), actor=actor, action=action, data=data, created_at=utcnow())
        )

    async def audit_list(self):
        async with self.engine.connect() as db:
            rows = (await db.execute(select(s.audit).order_by(s.audit.c.created_at.desc()).limit(100))).mappings()
            return [dict(row) for row in rows]

    async def cleanup(self):
        now = utcnow()
        async with self.engine.begin() as db:
            await db.execute(delete(s.cache).where(s.cache.c.expires_at < now))
            await db.execute(delete(s.rate).where(s.rate.c.minute < int(now.timestamp()) // 60 - 120))
            cutoff = now - timedelta(days=self.settings.history_days)
            await db.execute(delete(s.history).where(s.history.c.created_at < cutoff))
            await db.execute(delete(s.audit).where(s.audit.c.created_at < cutoff))
            cutoff = now - timedelta(days=self.settings.evidence_days)
            await db.execute(delete(s.evidence).where(s.evidence.c.stored_at < cutoff))
            await db.execute(delete(s.versions).where(s.versions.c.last_seen < cutoff))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
