"""Database sessions.

In AWS each service connects as its own database user (svc_<service>) with a
short-lived IAM token, so no password is stored anywhere. Locally, DATABASE_URL is
used as given.
"""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _iam_engine() -> Engine:
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
    rds = boto3.client("rds")

    @event.listens_for(engine, "do_connect")
    def _token(dialect, conn_rec, cargs, cparams):  # noqa: ARG001
        cparams["password"] = rds.generate_db_auth_token(host, port, user)

    return engine


@lru_cache(maxsize=1)
def engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if url:
        return create_engine(url)
    return _iam_engine()


def session_factory(schema_translate_map: dict | None = None) -> sessionmaker:
    eng = engine()
    if schema_translate_map is not None:
        eng = eng.execution_options(schema_translate_map=schema_translate_map)
    return sessionmaker(bind=eng, expire_on_commit=False)


def get_session(factory: sessionmaker) -> Iterator[Session]:
    with factory() as session:
        yield session
