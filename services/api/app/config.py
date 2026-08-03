pass

import os
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(RuntimeError):
    pass


def parse_postgresql_url(raw_url: str, variable_name: str) -> URL:
    pass

    if not raw_url.strip():
        raise DatabaseConfigurationError(f"{variable_name} is required.")

    try:
        url = make_url(raw_url)
    except ArgumentError:
        raise DatabaseConfigurationError(
            f"{variable_name} is not a valid database URL."
        ) from None

    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseConfigurationError(
            f"{variable_name} must use PostgreSQL with the psycopg driver."
        )
    if not url.host or not url.database or not url.username:
        raise DatabaseConfigurationError(
            f"{variable_name} must include a host, database, and username."
        )

    ssl_mode = url.query.get("sslmode")
    if ssl_mode not in {"require", "verify-ca", "verify-full"}:
        raise DatabaseConfigurationError(
            f"{variable_name} must require TLS with sslmode."
        )




    return url.set(drivername="postgresql+psycopg")


@dataclass(frozen=True)
class DatabaseSettings:
    pass

    database_url: URL

    @classmethod
    def from_environment(cls) -> "DatabaseSettings":
        return cls(
            database_url=parse_postgresql_url(
                os.environ.get("DATABASE_URL", ""),
                "DATABASE_URL",
            )
        )
