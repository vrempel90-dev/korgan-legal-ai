from korgan_legal_ai.db.engine import normalize_database_url


def test_normalizes_legacy_postgres_scheme_to_psycopg3() -> None:
    assert (
        normalize_database_url("postgres://user:pass@db.internal:5432/app")
        == "postgresql+psycopg://user:pass@db.internal:5432/app"
    )


def test_normalizes_plain_postgresql_scheme_to_psycopg3() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@db.internal:5432/app")
        == "postgresql+psycopg://user:pass@db.internal:5432/app"
    )


def test_keeps_explicit_psycopg3_and_non_postgres_urls_unchanged() -> None:
    explicit = "postgresql+psycopg://user:pass@db.internal:5432/app"
    sqlite = "sqlite+pysqlite:///:memory:"
    assert normalize_database_url(explicit) == explicit
    assert normalize_database_url(sqlite) == sqlite
