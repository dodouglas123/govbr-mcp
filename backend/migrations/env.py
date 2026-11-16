from alembic import context
from sqlalchemy import create_engine, pool

from govbr.schema import metadata
from govbr.settings import Settings

url = Settings().database_url.get_secret_value()


def run() -> None:
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        # Um único processo aplica as migrações mesmo durante um reinício simultâneo.
        connection.exec_driver_sql("SELECT pg_advisory_lock(80479531)")
        connection.commit()
        try:
            context.configure(connection=connection, target_metadata=metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(80479531)")
            connection.commit()
    engine.dispose()


run()
