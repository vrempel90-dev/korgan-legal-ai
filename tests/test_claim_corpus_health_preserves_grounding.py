"""Устаревший снимок корпуса не должен оставлять иск вообще без права.

``enforce_claim_corpus_health`` — правильный по замыслу temporal-validity gate:
он ловит момент, когда документ опирается на снимок официального источника,
который давно не сверялся, повреждён или не содержит нужной статьи.

Но его реакция — ``draft.legal_basis = []`` — уничтожала уже проверенную
работу. К этому моменту ``claim_filing_accuracy._ground_legal_basis`` уже
сверил цитату с текстом статьи в корпусе: норма реальная, сомнение только в
свежести снимка. Обнуление превращало иск в документ без раздела «Правовое
обоснование» — профессионально это хуже, чем ссылка с явной пометкой о
необходимости сверить редакцию, и прямо противоречит правилу «неподтверждённую
ссылку нельзя ТИХО выпускать клиенту»: тихо исчезала как раз подтверждённая.

Триггер не экзотический. Достаточно, чтобы фоновое обновление корпуса не
проходило неделю или чтобы разбор акта не положил конкретную статью в снимок.

Правильное поведение — controlled verification path:
статус понижается, замечание добавляется, ссылка остаётся и несёт видимую
пометку проверки.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from korgan.claim_corpus_health import LEGAL_GROUNDING_PREFIX, enforce_claim_corpus_health
from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_SPECIAL, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
ARTICLE_627 = (
    "Если подрядчик не приступает своевременно к исполнению договора подряда или выполняет "
    "работу настолько медленно, что окончание ее к сроку становится явно невозможным, "
    "заказчик вправе отказаться от договора и потребовать возмещения убытков."
)
GROUNDED_BASIS = f"{ARTICLE_627} Правовое основание: статья 627 ГК РК."


def _corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, loaded_at: str) -> Path:
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(
            ACT_GK_SPECIAL,
            "K990000409_",
            "Гражданский кодекс Республики Казахстан (Особенная часть)",
            GK_SPECIAL_URL,
            "2026-01-10",
            loaded_at,
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="627",
            item_no=None,
            heading="Права заказчика во время выполнения работы подрядчиком",
            body=ARTICLE_627,
            edition_date="2026-01-10",
            url=GK_SPECIAL_URL,
            sort_key=627,
        )
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[verified_claim_line(ARTICLE_627, "статья 627 ГК РК", ARTICLE_627, GK_SPECIAL_URL)],
        unverified_claims=[],
        source_urls=[GK_SPECIAL_URL],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о возврате предоплаты",
        court="Медеуский районный суд",
        claimant=["Ахметова Гульнара Сериковна, ИИН 000000000001"],
        defendant=["ТОО «Компания», БИН 000000000002"],
        price_of_claim="2 300 000 тенге",
        facts=["Ответчик не выполнил работы и не возвратил 2 300 000 тенге."],
        legal_basis=[GROUNDED_BASIS],
        requests=["Взыскать 2 300 000 тенге предоплаты."],
        attachments=["Договор подряда"],
        verification_notes=[],
        source_urls=[GK_SPECIAL_URL],
    )


def test_stale_snapshot_keeps_grounding_and_marks_it(tmp_path, monkeypatch) -> None:
    _corpus(tmp_path, monkeypatch, loaded_at="2026-01-10")
    draft = _draft()

    enforce_claim_corpus_health(_research(), draft, today=date(2026, 3, 1))

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any(note.startswith(LEGAL_GROUNDING_PREFIX) for note in draft.verification_notes)
    # Проверенная норма осталась в документе и несёт видимую пометку.
    assert draft.legal_basis, "иск не должен остаться без правового обоснования"
    assert any("статья 627" in item.lower() for item in draft.legal_basis)
    assert any("[ТРЕБУЕТ ПРОВЕРКИ" in item for item in draft.legal_basis)


def test_fresh_snapshot_leaves_grounding_untouched(tmp_path, monkeypatch) -> None:
    _corpus(tmp_path, monkeypatch, loaded_at="2026-02-27")
    draft = _draft()

    enforce_claim_corpus_health(_research(), draft, today=date(2026, 3, 1))

    assert draft.status == VerificationStatus.VERIFIED
    assert draft.verification_notes == []
    assert draft.legal_basis == [GROUNDED_BASIS]


def test_marker_is_not_applied_twice_on_repeated_release_passes(tmp_path, monkeypatch) -> None:
    """Финализация иска вызывается дважды; пометка не должна дублироваться."""
    _corpus(tmp_path, monkeypatch, loaded_at="2026-01-10")
    draft = _draft()

    enforce_claim_corpus_health(_research(), draft, today=date(2026, 3, 1))
    first = list(draft.legal_basis)
    enforce_claim_corpus_health(_research(), draft, today=date(2026, 3, 1))

    assert draft.legal_basis == first
    assert draft.legal_basis[0].count("[ТРЕБУЕТ ПРОВЕРКИ") == 1


def test_missing_article_in_snapshot_still_keeps_the_claim_grounded(tmp_path, monkeypatch) -> None:
    """Пробел в разборе акта не должен обнулять право во всём иске."""
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(
            ACT_GK_SPECIAL,
            "K990000409_",
            "Гражданский кодекс Республики Казахстан (Особенная часть)",
            GK_SPECIAL_URL,
            "2026-02-27",
            "2026-02-27",
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="626",
            item_no=None,
            heading="Другая статья",
            body="Текст другой статьи, длинный настолько, чтобы пройти проверку пригодности цитаты.",
            edition_date="2026-02-27",
            url=GK_SPECIAL_URL,
            sort_key=626,
        )
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)

    draft = _draft()
    enforce_claim_corpus_health(_research(), draft, today=date(2026, 3, 1))

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.legal_basis, "иск не должен остаться без правового обоснования"
    assert any("[ТРЕБУЕТ ПРОВЕРКИ" in item for item in draft.legal_basis)
