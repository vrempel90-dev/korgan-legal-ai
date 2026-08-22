from __future__ import annotations

from pathlib import Path

import pytest

from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_SPECIAL, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.provision_check import verified_claim_line

GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
ARTICLE_684 = "Если иное не предусмотрено договором возмездного оказания услуг, исполнитель обязан оказать услуги лично."
ARTICLE_685 = "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, которые указаны в договоре возмездного оказания услуг."


def _claim() -> str:
    return verified_claim_line(
        "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, которые указаны в договоре возмездного оказания услуг.",
        "статья 685 ГК РК (Особенная часть)",
        ARTICLE_685,
        GK_SPECIAL_URL,
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Алмалинский районный суд",
        claimant=["Иванов Иван Иванович, ИИН 900101300001, г. Алматы"],
        defendant=["Петров Петр Петрович, ИИН 900101300002, г. Алматы"],
        price_of_claim="100 000 тенге",
        facts=["Услуги оказаны, оплата 100 000 тенге не произведена."],
        legal_basis=["Модельное основание."],
        requests=["Взыскать 100 000 тенге."],
        attachments=["Договор", "Акт"],
        verification_notes=[],
        source_urls=[],
        state_duty="",
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[_claim()],
        unverified_claims=[],
        source_urls=[GK_SPECIAL_URL],
        notes=[],
    )


def _context() -> str:
    return (
        "Истец: Иванов Иван Иванович, ИИН 900101300001, г. Алматы.\n"
        "Ответчик: Петров Петр Петрович, ИИН 900101300002, г. Алматы.\n"
        "Договор оказания услуг. Услуги оказаны. Долг 100 000 тенге."
    )


def _build_corpus(
    path: Path,
    *,
    act_edition: str = "2026-08-22",
    loaded_at: str = "2026-08-22",
    provision_edition: str = "2026-08-22",
    include_cited_article: bool = True,
) -> None:
    with LegalCorpus(path) as db:
        db.upsert_act(
            ACT_GK_SPECIAL,
            "K990000409_",
            "Гражданский кодекс Республики Казахстан (Особенная часть)",
            GK_SPECIAL_URL,
            act_edition,
            loaded_at,
        )
        if include_cited_article:
            db.upsert_provision(
                act_id=ACT_GK_SPECIAL,
                article_no="685",
                item_no=None,
                heading="Оплата услуг",
                body=ARTICLE_685,
                edition_date=provision_edition,
                url=GK_SPECIAL_URL,
                sort_key=685,
            )
        else:
            # Keep the SQLite corpus non-empty so open_corpus() succeeds while
            # the exact required provision is deliberately absent.
            db.upsert_provision(
                act_id=ACT_GK_SPECIAL,
                article_no="684",
                item_no=None,
                heading="Исполнение договора возмездного оказания услуг",
                body=ARTICLE_684,
                edition_date=provision_edition or "2026-08-22",
                url=GK_SPECIAL_URL,
                sort_key=684,
            )


def _assert_fail_closed() -> None:
    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.legal_basis == []
    assert any(str(note).startswith("LEGAL_GROUNDING: ") for note in draft.verification_notes)


def test_disabled_corpus_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    _assert_fail_closed()


def test_missing_corpus_file_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", tmp_path / "missing.sqlite3")
    _assert_fail_closed()


def test_unreadable_corpus_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    _assert_fail_closed()


def test_partial_corpus_missing_cited_article_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "partial.sqlite3"
    _build_corpus(path, include_cited_article=False)
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    _assert_fail_closed()


@pytest.mark.parametrize(
    ("act_edition", "loaded_at", "provision_edition"),
    [
        ("2026-08-01", "2026-08-01", "2026-08-01"),
        ("", "2026-08-22", "2026-08-22"),
        ("2026-08-22", "", "2026-08-22"),
        ("2026-08-22", "2026-08-22", ""),
    ],
)
def test_stale_or_undated_corpus_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    act_edition: str,
    loaded_at: str,
    provision_edition: str,
) -> None:
    path = tmp_path / "unhealthy.sqlite3"
    _build_corpus(
        path,
        act_edition=act_edition,
        loaded_at=loaded_at,
        provision_edition=provision_edition,
    )
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    _assert_fail_closed()


def test_fresh_complete_corpus_still_releases_grounded_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "healthy.sqlite3"
    _build_corpus(path)
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)

    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)

    assert draft.status == VerificationStatus.VERIFIED
    assert any("статья 685" in item.lower() for item in draft.legal_basis)
    assert not any(str(note).startswith("LEGAL_GROUNDING: ") for note in draft.verification_notes)
