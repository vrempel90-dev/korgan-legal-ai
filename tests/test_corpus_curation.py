"""Curation refuses incomplete records and never overwrites a wording silently."""
from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from korgan_legal_ai.corpus.curation import (
    CorpusCurator,
    CurationError,
    NormSubmission,
    check_source,
)
from korgan_legal_ai.corpus.models import default_next_review
from korgan_legal_ai.corpus.repository import LegalNormRepository

DB_URL = os.getenv("TEST_DATABASE_URL")

FULL_TEXT = (
    "Проверочная запись для теста инструмента наполнения корпуса. Настоящий текст не является "
    "нормой права и подлежит замене дословным текстом статьи из официального источника."
)


def _submission(**overrides) -> NormSubmission:
    payload = {
        "code_id": "TEST_CODE",
        "article_number": "1000",
        "text": FULL_TEXT,
        "effective_from": date(2026, 1, 1),
        "source_url": "https://adilet.zan.kz/rus/docs/TESTDOC",
        "reviewed_by": "Тестовый юрист",
        "law_name": "Тестовый кодекс",
        "applicable_document_types": ("claim",),
    }
    payload.update(overrides)
    return NormSubmission(**payload)


def test_default_review_date_is_six_months_out_and_survives_month_ends() -> None:
    assert default_next_review(date(2026, 8, 15)) == date(2027, 2, 15)
    # 31 August has no counterpart in February; the date clamps instead of overflowing.
    assert default_next_review(date(2026, 8, 31)) == date(2027, 2, 28)
    assert default_next_review(date(2024, 8, 31)) == date(2025, 2, 28)
    assert default_next_review(date(2026, 12, 31)) == date(2027, 6, 30)


def test_missing_required_fields_are_all_reported_at_once() -> None:
    problems = NormSubmission(
        code_id="",
        article_number="",
        text="",
        effective_from=date(2026, 1, 1),
        source_url="",
        reviewed_by="",
    ).validate()

    joined = "; ".join(problems)
    for field in ("code_id", "article_number", "source_url", "reviewed_by"):
        assert field in joined


def test_a_text_too_short_to_be_a_quotation_is_refused() -> None:
    """A citation reproduces the norm; a truncated quote is a misquote."""
    problems = _submission(text="слишком коротко").validate()

    assert any("слишком короткий" in problem for problem in problems)


def test_unknown_document_types_are_refused_with_the_allowed_list() -> None:
    problems = _submission(applicable_document_types=("claim", "нечто")).validate()

    assert any("неизвестные типы дел" in problem for problem in problems)
    assert any("pretrial_demand" in problem for problem in problems)


def test_effective_range_must_not_be_inverted() -> None:
    problems = _submission(effective_to=date(2025, 1, 1)).validate()

    assert any("не может быть раньше" in problem for problem in problems)


def test_source_check_accepts_official_and_warns_on_anything_else() -> None:
    official = check_source("https://adilet.zan.kz/rus/docs/K940001000_")
    assert official.official

    unofficial = check_source("https://legal-blog.example/gk-272")
    assert not unofficial.official
    # The warning explains the downstream consequence, not just that the domain is unknown.
    assert "не появится" in unofficial.message

    assert not check_source("http://adilet.zan.kz/rus/docs/X").official
    assert not check_source("").official


@pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL is required")
class TestAgainstDatabase:
    @pytest.fixture()
    def curator(self) -> CorpusCurator:
        assert DB_URL is not None
        subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": DB_URL},
        )
        engine = create_engine(DB_URL)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM legal_norms WHERE code_id = 'TEST_CODE'"))
        return CorpusCurator(LegalNormRepository(engine))

    def test_add_stores_a_canonical_norm_with_review_metadata(self, curator) -> None:
        result = curator.add(_submission())

        assert result.norm.reviewed_by == "Тестовый юрист"
        assert result.norm.reviewed_at is not None
        assert result.norm.next_review_date is not None
        assert result.norm.next_review_date > date.today()
        assert result.norm.applicable_document_types == ["claim"]

        stored = curator.repository.get_canonical_for_date(
            code_id="TEST_CODE", article_number="1000", event_date=date(2026, 6, 1)
        )
        assert stored is not None and stored.text == FULL_TEXT

    def test_unofficial_source_needs_an_explicit_override(self, curator) -> None:
        submission = _submission(source_url="https://legal-blog.example/x")

        with pytest.raises(CurationError, match="allow-unofficial-source"):
            curator.add(submission)

        result = curator.add(submission, allow_unofficial_source=True)
        # It is stored, and the warning states plainly that it will not reach a document.
        assert result.warnings and "не появится" in result.warnings[0]

    def test_adding_the_same_redaction_twice_is_refused(self, curator) -> None:
        curator.add(_submission())

        with pytest.raises(CurationError, match="уже есть в корпусе"):
            curator.add(_submission())

    def test_update_opens_a_new_redaction_and_keeps_the_previous_one(self, curator) -> None:
        curator.add(_submission())

        result = curator.update(
            _submission(effective_from=date(2026, 7, 1), text=FULL_TEXT + " Редакция вторая.")
        )

        assert result.superseded is not None
        # The old wording is closed the day before the new one starts, not deleted.
        assert result.superseded.effective_to == date(2026, 6, 30)

        versions = curator.repository.get_by_locator(code_id="TEST_CODE", article_number="1000")
        assert len(versions) == 2

        # A document produced under the old wording is still reproducible against it.
        old = curator.repository.get_canonical_for_date(
            code_id="TEST_CODE", article_number="1000", event_date=date(2026, 3, 1)
        )
        new = curator.repository.get_canonical_for_date(
            code_id="TEST_CODE", article_number="1000", event_date=date(2026, 8, 1)
        )
        assert old is not None and "Редакция вторая" not in old.text
        assert new is not None and "Редакция вторая" in new.text

    def test_update_refuses_to_reuse_the_current_effective_date(self, curator) -> None:
        curator.add(_submission())

        with pytest.raises(CurationError, match="новую дату вступления в силу"):
            curator.update(_submission(text=FULL_TEXT + " Другой текст."))

    def test_in_place_correction_is_possible_but_must_be_asked_for(self, curator) -> None:
        curator.add(_submission())

        result = curator.update(
            _submission(text=FULL_TEXT + " Исправлена опечатка."), correct_in_place=True
        )

        assert result.superseded is None
        versions = curator.repository.get_by_locator(code_id="TEST_CODE", article_number="1000")
        assert len(versions) == 1
        assert "опечатк" in versions[0].text

    def test_update_of_an_unknown_norm_points_at_add(self, curator) -> None:
        with pytest.raises(CurationError, match="add-norm"):
            curator.update(_submission(article_number="7777"))

    def test_overdue_norms_appear_in_the_review_queue(self, curator) -> None:
        curator.add(_submission(next_review_date=date(2026, 9, 1)))

        assert curator.due_for_review(as_of=date(2026, 8, 20)) == []

        overdue = curator.due_for_review(as_of=date(2026, 10, 1))
        assert [norm.article_number for norm in overdue if norm.code_id == "TEST_CODE"] == ["1000"]

    def test_a_norm_is_marked_overdue_only_after_its_review_date(self, curator) -> None:
        result = curator.add(_submission(next_review_date=date(2026, 9, 1)))

        assert not result.norm.review_overdue(date(2026, 8, 31))
        assert result.norm.review_overdue(date(2026, 9, 2))

    def test_review_metadata_round_trips_through_storage(self, curator) -> None:
        moment = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
        norm = _submission(applicable_document_types=("claim", "appeal")).to_norm(
            reviewed_at=moment
        )
        curator.repository.upsert(norm)

        stored = curator.repository.get_canonical_for_date(
            code_id="TEST_CODE", article_number="1000", event_date=date(2026, 6, 1)
        )
        assert stored is not None
        assert sorted(stored.applicable_document_types) == ["appeal", "claim"]
        assert stored.next_review_date == date(2027, 2, 15)
