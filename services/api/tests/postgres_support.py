pass

import os

from sqlalchemy.engine import URL

from app.config import parse_postgresql_url


TEST_DATABASE_CONFIRMATION = "promptql-test-database"


def _normalized_neon_identity(url: URL) -> tuple[str, int | None, str | None]:
    host = (url.host or "").lower()
    first_label, separator, remainder = host.partition(".")
    if first_label.endswith("-pooler"):
        first_label = first_label.removesuffix("-pooler")
        host = first_label + (separator + remainder if separator else "")
    return host, url.port, url.database


def load_safe_test_database_url() -> URL | None:
    pass

    raw_test_url = os.environ.get("TEST_DATABASE_URL", "")
    if not raw_test_url:
        return None
    if (
        os.environ.get("TEST_DATABASE_CONFIRMATION")
        != TEST_DATABASE_CONFIRMATION
    ):
        raise RuntimeError(
            "TEST_DATABASE_CONFIRMATION must identify a dedicated test database."
        )

    test_url = parse_postgresql_url(raw_test_url, "TEST_DATABASE_URL")
    raw_application_url = os.environ.get("DATABASE_URL", "")
    if raw_application_url:
        application_url = parse_postgresql_url(
            raw_application_url,
            "DATABASE_URL",
        )
        if raw_test_url == raw_application_url or (
            _normalized_neon_identity(test_url)
            == _normalized_neon_identity(application_url)
        ):
            raise RuntimeError(
                "TEST_DATABASE_URL must not identify the application database."
            )
    return test_url
