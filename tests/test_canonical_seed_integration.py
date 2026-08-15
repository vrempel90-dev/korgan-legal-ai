from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.repository import LegalNormRepository
from korgan_legal_ai.corpus.seed import load_canonical_seed

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")

EXPECTED = {
    ("GK_RK_GENERAL", "353", "", ""): date(2021, 1, 1),
    ("GK_RK_SPECIAL", "683", "", ""): date(2020, 12, 31),
    ("GK_RK_SPECIAL", "686", "", ""): date(1999, 7, 1),
    ("GK_RK_SPECIAL", "964", "", ""): date(2015, 4, 21),
    ("GK_RK_SPECIAL", "967", "", ""): date(2017, 3, 12),
    ("GPK_RK", "73", "", ""): date(2022, 1, 1),
    ("LABOR_RK", "22", "1", "21"): date(2016, 1, 1),
    ("LABOR_RK", "192", "", "3"): date(2026, 6, 8),
    ("LABOR_RK", "194", "", "4"): date(2026, 6, 8),
    ("PDPA_94_V", "2", "", ""): date(2013, 11, 25),
    ("PDPA_94_V", "31", "", ""): date(2013, 11, 25),
}


def test_manual_reference_seed_is_canonical_and_complete() -> None:
    assert DB_URL is not None
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": DB_URL},
    )
    engine = create_engine(DB_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE legal_research_candidates, legal_norms CASCADE"))
    repo = LegalNormRepository(engine)
    seed = Path(__file__).parents[1] / "data" / "canonical" / "kz_reference_norms.yaml"
    loaded = load_canonical_seed(seed, repo)
    assert len(loaded) == len(EXPECTED)
    for locator, expected_date in EXPECTED.items():
        code_id, article, part, point = locator
        rows = repo.get_by_locator(
            code_id=code_id,
            article_number=article,
            part=part,
            point=point,
        )
        assert len(rows) == 1, locator
        norm = rows[0]
        assert norm.status.value == "canonical"
        assert norm.source_url.startswith("https://adilet.zan.kz/")
        assert norm.effective_from == expected_date
        assert norm.reviewed_by
        assert norm.text.strip()
