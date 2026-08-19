"""Alembic migration environment.

Reads DATABASE_URL_MIGRATIONS via app.config.get_settings() rather than
a static alembic.ini value -- Supabase's session pooler (a stable,
non-multiplexed connection), distinct from app/db.py's runtime pool
(DATABASE_URL_RUNTIME, the transaction pooler). Alembic itself runs
migrations over a sync driver (psycopg) regardless of environment;
runtime queries always use asyncpg (app/db.py) -- the two never share a
connection. `app` is importable here because alembic.ini's
`prepend_sys_path = .` adds backend/ (where alembic.ini lives) to
sys.path.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # no ORM models -- migrations are hand-written SQL


def _sync_database_url() -> str:
    """DATABASE_URL_MIGRATIONS, rewritten for Alembic's sync (psycopg)
    driver.

    app/db.py's asyncpg pool wants a plain `postgresql://` DSN.
    SQLAlchemy (which Alembic uses under the hood) needs the `+psycopg`
    dialect suffix to pick psycopg3 instead of defaulting to psycopg2
    (not installed). Same connection string, different driver, only
    here.
    """
    url = get_settings().database_url_migrations
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Emit migration SQL without a live DB connection."""
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations directly against a live DB connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sync_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
