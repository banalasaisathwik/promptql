import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import UserAlreadyExistsError  # noqa: E402
from app.config import DatabaseSettings, DemoAccountSettings  # noqa: E402
from app.database.engine import create_database_engine, create_session_factory  # noqa: E402
from app.database.postgres_user_repository import PostgresUserRepository  # noqa: E402


def main() -> None:
    demo_account_settings = DemoAccountSettings.from_environment()
    database_settings = DatabaseSettings.from_environment()
    engine = create_database_engine(database_settings)
    session_factory = create_session_factory(engine)
    user_repository = PostgresUserRepository(session_factory)

    try:
        user_repository.create_user(
            demo_account_settings.email,
            demo_account_settings.password,
            is_demo=True,
        )
        print(f"Created demo account: {demo_account_settings.email}")
    except UserAlreadyExistsError:
        print(f"Demo account already exists, nothing to do: {demo_account_settings.email}")

    print("")
    print("Demo account credentials (also served by GET /v1/demo-account):")
    print(f"  email:    {demo_account_settings.email}")
    print(f"  password: {demo_account_settings.password}")


if __name__ == "__main__":
    main()
