from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from korgan.claim_corpus_health import STALE_SNAPSHOT_MARKER
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
    act_edition: str | None = None,
    loaded_at: str | None = None,
    provision_edition: str | None = None,
    include_cited_article: bool = True,
) -> None:
    fresh_date = date.today().isoformat()
    act_edition = fresh_date if act_edition is None else act_edition
    loaded_at = fresh_date if loaded_at is None else loaded_at
    provision_edition = fresh_date if provision_edition is None else provision_edition

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
                edition_date=provision_edition or fresh_date,
                url=GK_SPECIAL_URL,
                sort_key=684,
            )


def _assert_fail_closed() -> None:
    """Корпус есть, но нужной статьи в нём нет — сверять было нечего.

    Собранный корпус — авторитетный источник: если он не содержит
    процитированного положения, ссылку нечем подтвердить, и в судебный текст не
    выпускается ничего.
    """
    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.legal_basis == []
    assert any(str(note).startswith("LEGAL_GROUNDING: ") for note in draft.verification_notes)


def _assert_source_bound_fallback() -> None:
    """Локальной сверки нет — работает source-bound исследование.

    Это не то же самое, что «сверять было нечего»: вывод уже связан с реально
    открытым официальным актом Adilet, к нему приложена дословная выдержка
    нормы, и пересказ с ней не расходится. Стирать такое правовое основание
    значит отдать клиенту иск вообще без права — README обещает обратное
    («rather than emitting a claim with no legal basis»).

    Чего подтвердить нельзя без корпуса — что выдержка принадлежит именно
    названному номеру статьи. Поэтому иск остаётся документом для юриста:
    статус понижен, а в замечаниях стоит прямое указание сверить номера и
    редакции перед подачей. Готовым к подаче он в этом режиме быть не может.
    """
    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("статья 685" in item.lower() for item in draft.legal_basis)
    assert any(
        str(note).startswith("FILING_ACTION: ") and "сверить номера" in str(note)
        for note in draft.verification_notes
    ), draft.verification_notes
    # Служебных пометок внутри самого судебного текста быть не должно.
    assert all(STALE_SNAPSHOT_MARKER not in item for item in draft.legal_basis)


def _assert_nothing_to_release() -> None:
    """Ни один вывод не связан с официальным источником — выпускать нечего."""
    draft = _draft()
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        # Вывод без связки «статья + текст нормы + официальный источник».
        verified_claims=["Заказчик обязан оплатить оказанные услуги."],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )
    finalize_professional_claim(_context(), research, draft)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.legal_basis == []
    assert any(str(note).startswith("LEGAL_GROUNDING: ") for note in draft.verification_notes)


def _assert_controlled_verification_path() -> None:
    """Снимок несвеж или недатирован, но сама норма сверена с текстом статьи.

    Это другой случай, чем недоступный корпус. Цитата уже сопоставлена с
    официальным текстом; под сомнением только свежесть снимка. Стирать здесь
    правовое обоснование значит отдать клиенту иск вообще без права — и молча
    уничтожить как раз подтверждённую работу. Документ переводится в
    контролируемый путь проверки: статус понижен, замечание записано, ссылка
    осталась и несёт видимую пометку сверки, поэтому уйти как готовый к подаче
    он не может.
    """
    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any(str(note).startswith("LEGAL_GROUNDING: ") for note in draft.verification_notes)
    assert any("статья 685" in item.lower() for item in draft.legal_basis)
    assert all(STALE_SNAPSHOT_MARKER in item for item in draft.legal_basis)


def test_disabled_corpus_falls_back_to_source_bound_research(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    _assert_source_bound_fallback()


def test_missing_corpus_file_falls_back_to_source_bound_research(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", tmp_path / "missing.sqlite3")
    _assert_source_bound_fallback()


def test_unreadable_corpus_falls_back_to_source_bound_research(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    _assert_source_bound_fallback()


def test_without_corpus_unbound_conclusions_are_still_not_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ от корпуса не открывает дорогу праву по памяти модели."""
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    _assert_nothing_to_release()


def test_without_corpus_unofficial_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Источник не с официального акта РК правовым основанием не становится."""
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    draft = _draft()
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            verified_claim_line(
                "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, "
                "которые указаны в договоре возмездного оказания услуг.",
                "статья 685 ГК РК (Особенная часть)",
                ARTICLE_685,
                "https://online.zakon.kz/document/?doc_id=1006061",
            )
        ],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )
    finalize_professional_claim(_context(), research, draft)

    assert draft.legal_basis == []
    assert any("не является официальным актом" in str(note) for note in draft.verification_notes)


def test_partial_corpus_missing_cited_article_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "partial.sqlite3"
    _build_corpus(path, include_cited_article=False)
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    _assert_fail_closed()


@pytest.mark.parametrize(
    ("act_edition", "loaded_at", "provision_edition"),
    [
        ("2000-01-01", "2000-01-01", "2000-01-01"),
        ("", None, None),
        (None, "", None),
        (None, None, ""),
    ],
)
def test_stale_snapshot_or_undated_revision_enters_controlled_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    act_edition: str | None,
    loaded_at: str | None,
    provision_edition: str | None,
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
    _assert_controlled_verification_path()


def test_old_legal_revision_is_valid_when_official_snapshot_was_fetched_today(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "unchanged-law.sqlite3"
    _build_corpus(
        path,
        act_edition="2020-01-01",
        loaded_at=date.today().isoformat(),
        provision_edition="2020-01-01",
    )
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)

    draft = _draft()
    finalize_professional_claim(_context(), _research(), draft)

    assert draft.status == VerificationStatus.VERIFIED
    assert any("статья 685" in item.lower() for item in draft.legal_basis)


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


def test_without_corpus_act_named_in_citation_must_match_the_opened_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Названный акт и открытый источник должны совпадать.

    Статья 685 живёт в Особенной части ГК. Ссылка на Общую часть с тем же
    номером — уже другая норма, и без локального корпуса эту подмену больше
    нечем заметить: сама выдержка настоящая, источник официальный, расхождения
    пересказа нет.
    """
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    draft = _draft()
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            verified_claim_line(
                "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, "
                "которые указаны в договоре возмездного оказания услуг.",
                "статья 685 ГК РК (Особенная часть)",
                ARTICLE_685,
                "https://adilet.zan.kz/rus/docs/K940001000_",
            )
        ],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )
    finalize_professional_claim(_context(), research, draft)

    assert draft.legal_basis == []
    assert any("называет один акт, а открыт другой" in str(note) for note in draft.verification_notes)
