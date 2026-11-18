"""Database sessions.

In AWS the app connects as its database user (DB_USER, app_rw) with a short-lived IAM
token, so no password is stored anywhere. Locally, DATABASE_URL is
used as given.
"""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _iam_engine() -> Engine:
    """IAM-token login, on Lambda only. Without DATABASE_URL anywhere else this refuses,
    rather than sign tokens with whatever AWS credentials the shell happens to have."""
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):  # auth.on_lambda, without importing auth
        raise RuntimeError("DATABASE_URL is not set; IAM database login runs on Lambda only")
    import boto3  # pinned in app/pyproject.toml; loaded only on this IAM path

    host = os.environ["DB_HOST"]
    port = int(os.environ.get("DB_PORT", "5432"))
    user = os.environ["DB_USER"]
    engine = create_engine(
        f"postgresql+psycopg://{user}@{host}:{port}/{os.environ['DB_NAME']}",
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    from .regions import check_endpoints, configured_region  # tenant data stays in India (D-094)

    check_endpoints()
    rds = boto3.client("rds", region_name=configured_region())

    @event.listens_for(engine, "do_connect")
    def _token(dialect, conn_rec, cargs, cparams):  # noqa: ARG001
        cparams["password"] = rds.generate_db_auth_token(host, port, user)

    return engine


@lru_cache(maxsize=1)
def engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if url:
        return create_engine(url, **engine_options(url))
    return _iam_engine()


def engine_options(url: str) -> dict:
    """Local and test use only: DATABASE_URL is never set in AWS, where the IAM engine above is used and is left
    as it is. A PostgreSQL server that cannot be reached fails in seconds, not after the operating system's own long
    wait. Only PostgreSQL drivers know `connect_timeout`; the in-memory SQLite some tests use does not.

    A connection kept in the pool can go dead without either side being told (a laptop that slept, Docker Desktop or WSL
    pausing its network). Without these settings the next request that draws it waits for the operating system's own
    retransmit limit, many minutes, while the pages that need no database (/health) still answer: sign-in and refresh
    then stall until the web app gives up at 20 seconds. So a dead connection is noticed within seconds (keepalives and
    `tcp_user_timeout`, in milliseconds, so an unanswered packet fails the call), checked before each use (pre-ping), and
    replaced rather than reused (recycle)."""
    if make_url(url).get_backend_name() == "postgresql":
        return {
            "connect_args": {
                "connect_timeout": 5,
                "keepalives": 1,
                "keepalives_idle": 15,
                "keepalives_interval": 5,
                "keepalives_count": 3,
                "tcp_user_timeout": 5000,
            },
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    return {}


def session_factory(schema_translate_map: dict | None = None) -> sessionmaker:
    eng = engine()
    if schema_translate_map is not None:
        eng = eng.execution_options(schema_translate_map=schema_translate_map)
    return sessionmaker(bind=eng, expire_on_commit=False)


def get_session(factory: sessionmaker) -> Iterator[Session]:
    with factory() as session:
        yield session
