from __future__ import annotations

import os
import subprocess
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.models import CorpusStatus, LegalNorm
from korgan_legal_ai.corpus.repository import LegalNormRepository


DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")


@pytest.fixture(scope="module")
def repository() -> LegalNormRepository:
    assert DB_URL is not None
    env = {**os.environ, "DATABASE_URL": DB_URL}
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=env)
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    return LegalNormRepository(engine)


def test_versioned_norm_selection_and_idempotent_upsert(repository: LegalNormRepository) -> None:
    old = LegalNorm(
        code_id="TEST_CODE",
        article_number="1",
        text="Старая редакция",
        effective_from=date(2020, 1, 1),
        effective_to=date(2022, 12, 31),
        source_url="https://adilet.zan.kz/rus/docs/TEST",
        status=CorpusStatus.CANONICAL,
        reviewed_by="fixture-lawyer",
    )
    current = LegalNorm(
        code_id="TEST_CODE",
        article_number="1",
        text="Новая редакция",
        effective_from=date(2023, 1, 1),
        source_url="https://adilet.zan.kz/rus/docs/TEST",
        status=CorpusStatus.CANONICAL,
        reviewed_by="fixture-lawyer",
    )

    repository.upsert(old)
    repository.upsert(current)
    assert repository.count() == 2

    # Re-inserting the same source/article/version is an upsert, not a duplicate.
    current.text = "Новая редакция (исправленная загрузка)"
    repository.upsert(current)
    assert repository.count() == 2

    old_result = repository.get_canonical_for_date(
        code_id="TEST_CODE", article_number="1", event_date=date(2021, 6, 1)
    )
    new_result = repository.get_canonical_for_date(
        code_id="TEST_CODE", article_number="1", event_date=date(2024, 6, 1)
    )

    assert old_result is not None and old_result.text == "Старая редакция"
    assert new_result is not None and new_result.text == "Новая редакция (исправленная загрузка)"
