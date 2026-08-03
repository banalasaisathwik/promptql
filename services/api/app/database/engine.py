pass

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import DatabaseSettings
from app.runtime import RunPersistenceError


def create_database_engine(settings: DatabaseSettings) -> Engine:
    pass

    return create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 5},
        echo=False,
        hide_parameters=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    pass

    return sessionmaker(bind=engine, expire_on_commit=False)


def verify_database_ready(engine: Engine) -> None:
    pass

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_inspector = inspect(engine)
        required_tables = {"workflow_runs", "workflow_steps"}
        if not required_tables.issubset(database_inspector.get_table_names()):
            raise RunPersistenceError(
                "Runtime database migrations have not been applied."
            )
    except RunPersistenceError:
        raise
    except SQLAlchemyError:


        raise RunPersistenceError("Runtime persistence is unavailable.") from None
