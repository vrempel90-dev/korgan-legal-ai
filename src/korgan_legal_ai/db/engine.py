from __future__ import annotations

from sqlalchemy import Engine, create_engine


def normalize_database_url(database_url: str) -> str:
    """Normalize Railway/Postgres URLs for SQLAlchemy 2 + psycopg 3.

    Some managed Postgres providers still expose the legacy ``postgres://``
    scheme. SQLAlchemy 2 no longer provides a ``postgres`` dialect alias, and
    a plain ``postgresql://`` URL may select psycopg2 even though KORGAN ships
    psycopg 3. Keep explicit driver URLs untouched and normalize only the two
    provider-style schemes we own here.
    """
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def build_engine(database_url: str) -> Engine:
    return create_engine(normalize_database_url(database_url), pool_pre_ping=True)
