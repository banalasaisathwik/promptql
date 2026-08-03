pass

import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import parse_postgresql_url
from app.database.models import DatabaseModel


target_metadata = DatabaseModel.metadata


def migration_url():
    pass

    return parse_postgresql_url(
        os.environ.get("DATABASE_MIGRATION_URL", ""),
        "DATABASE_MIGRATION_URL",
    )


def run_migrations_offline() -> None:
    pass

    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    pass

    engine = create_engine(
        migration_url(),
        poolclass=pool.NullPool,
        echo=False,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
