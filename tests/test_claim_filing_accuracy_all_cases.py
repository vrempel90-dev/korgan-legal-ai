from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from korgan.claim_docx import build_claim_docx
from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX, LEGAL_GROUNDING_PREFIX
from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_GENERAL, ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.provision_check import verified_claim_line

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"

ARTICLE_684 = "Если иное не предусмотрено договором возмездного оказания услуг, исполнитель обязан оказать услуги лично."
ARTICLE_685 = "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, которые указаны в договоре возмездного оказания услуг."
ARTICLE_285 = "Должник, обязанный совершить одно из двух или нескольких действий, имеет право выбора предмета исполнения обязательства."
ARTICLE_349 = "Под нарушением обязательства понимается его неисполнение либо исполнение ненадлежащим образом, в том числе несвоевременное исполнение."
ARTICLE_27 = (
    "Специализированные межрайонные экономические суды рассматривают имущественные и неимущественные споры, "
    "сторонами которых являются юридические лица, индивидуальные предприниматели, если иное не установлено законом."
)
ARTICLE_700_SHARED = "Сторона обязана передать товар другой стороне в согласованный договором срок после получения письменного уведомления."


@pytest.fixture()
def grounding_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(ACT_GK_GENERAL, "K940001000_", "ГК РК (Общая часть)", GK_GENERAL_URL, "2026-08-22", "2026-08-22")
        db.upsert_act(ACT_GK_SPECIAL, "K990000409_", "ГК РК (Особенная часть)", GK_SPECIAL_URL, "2026-08-22", "2026-08-22")
        db.upsert_act(ACT_GPK, "K1500000377", "ГПК РК", GPK_URL, "2026-08-22", "2026-08-22")
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="684",
            item_no=None,
            heading="Исполнение договора возмездного оказания услуг",
            body=ARTICLE_684,
            edition_date="2026-08-22",
            url=GK_SPECIAL_URL,
            sort_key=684,
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="685",
            item_no=None,
            heading="Оплата услуг",
            body=ARTICLE_685,
            edition_date="2026-08-22",
            url=GK_SPECIAL_URL,
            sort_key=685,
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="700",
            item_no="1",
            heading="Тестовая составная норма",
            body=ARTICLE_700_SHARED,
            edition_date="2026-08-22",
            url=GK_SPECIAL_URL,
            sort_key=700,
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="700",
            item_no="2",
            heading="Тестовая составная норма",
            body=ARTICLE_700_SHARED,
            edition_date="2026-08-22",
            url=GK_SPECIAL_URL,
            sort_key=701,
        )
        db.upsert_provision(
            act_id=ACT_GK_GENERAL,
            article_no="285",
            item_no=None,
            heading="Исполнение альтернативного обязательства",
            body=ARTICLE_285,
            edition_date="2026-08-22",
            url=GK_GENERAL_URL,
            sort_key=285,
        )
        db.upsert_provision(
            act_id=ACT_GK_GENERAL,
            article_no="349",
            item_no=None,
            heading="Понятие нарушения обязательства",
            body=ARTICLE_349,
            edition_date="2026-08-22",
            url=GK_GENERAL_URL,
            sort_key=349,
        )
        db.upsert_provision(
            act_id=ACT_GPK,
            article_no="27",
            item_no=None,
            heading="Подсудность гражданских дел специализированным межрайонным экономическим судам",
            body=ARTICLE_27,
            edition_date="2026-08-22",
            url=GPK_URL,
            sort_key=27,
        )

    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _draft(*, mixed: bool = False) -> ClaimDraft:
    claimant = ["ТОО «Альфа Строй»", "БИН 190440012345", "Адрес: г. Алматы, ул. Абая, 10"]
    defendant = (
        ["Иванов Иван Иванович", "ИИН 900101300001", "Адрес: г. Алматы, ул. Толе би, 55"]
        if mixed
        else ["ТОО «Бета Сервис»", "БИН 200540067890", "Адрес: г. Алматы, ул. Толе би, 55"]
    )
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: районный суд города Алматы]",
        claimant=claimant,
        defendant=defendant,
        price_of_claim="1 800 000 тенге",
        facts=["Услуги оказаны и приняты, задолженность составляет 1 800 000 тенге."],
        legal_basis=["Модельное правовое обоснование."],
        requests=["Взыскать задолженность в размере 1 800 000 тенге."],
        attachments=["Договор", "Акт выполненных работ", "Досудебная претензия"],
        verification_notes=[],
        source_urls=[],
        state_duty="54 000 тенге (3% от цены иска, статья 665 Налогового кодекса РК)",
    )


def _research(*claims: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(claims),
        unverified_claims=[],
        source_urls=[GK_GENERAL_URL, GK_SPECIAL_URL, GPK_URL],
        notes=[],
    )


def _valid_service_claim() -> str:
    return verified_claim_line(
        "Заказчик обязан оплатить оказанные ему услуги в сроки и порядке, указанные в договоре.",
        "статья 685 ГК РК (Особенная часть)",
        ARTICLE_685,
        GK_SPECIAL_URL,
    )


def _case_context(*, mixed: bool = False, with_bank: bool = False) -> str:
    claimant = "ТОО «Альфа Строй», БИН 190440012345, г. Алматы, ул. Абая, 10"
    if with_bank:
        claimant += ", банковские реквизиты: IBAN KZ123456789012345678"
    defendant = (
        "Иванов Иван Иванович, ИИН 900101300001, г. Алматы, ул. Толе би, 55"
        if mixed
        else "ТОО «Бета Сервис», БИН 200540067890, г. Алматы, ул. Толе би, 55"
    )
    return f"Истец: {claimant}\nОтветчик: {defendant}\nДоговор оказания услуг. Долг 1 800 000 тенге."


def test_wrong_service_article_is_corrected_from_exact_corpus_quote(grounding_corpus: Path) -> None:
    wrong = verified_claim_line(
        "Заказчик обязан оплатить оказанные ему услуги в согласованный договором срок.",
        "статья 684 ГК РК (Особенная часть)",
        ARTICLE_685,
        GK_SPECIAL_URL,
    )
    draft = _draft()
    research = _research(wrong)

    finalize_professional_claim(_case_context(), research, draft)

    basis = "\n".join(draft.legal_basis)
    assert "статья 685" in basis
    assert "статья 684" not in basis
    assert any(note.startswith("LEGAL_CORRECTION:") for note in research.notes)


def test_wrong_breach_article_is_corrected_from_exact_corpus_quote(grounding_corpus: Path) -> None:
    wrong = verified_claim_line(
        "Неисполнение либо ненадлежащее исполнение обязанности является нарушением обязательства.",
        "статья 285 ГК РК (Общая часть)",
        ARTICLE_349,
        GK_GENERAL_URL,
    )
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(wrong), draft)

    basis = "\n".join(draft.legal_basis)
    assert "статья 349" in basis
    assert "статья 285" not in basis


def test_correct_article_remains_filing_facing(grounding_corpus: Path) -> None:
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(_valid_service_claim()), draft)

    assert any("статья 685" in item for item in draft.legal_basis)
    assert not any(note.startswith(LEGAL_GROUNDING_PREFIX) for note in draft.verification_notes)


def test_nonexistent_cited_part_cannot_fall_back_to_other_part(grounding_corpus: Path) -> None:
    wrong_part = verified_claim_line(
        "Сторона обязана передать товар в согласованный договором срок.",
        "часть 4 статьи 700 ГК РК (Особенная часть)",
        ARTICLE_700_SHARED,
        GK_SPECIAL_URL,
    )
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(wrong_part), draft)

    assert not draft.legal_basis
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any(note.startswith(LEGAL_GROUNDING_PREFIX) for note in draft.verification_notes)


def test_ambiguous_same_article_parts_are_not_auto_corrected(grounding_corpus: Path) -> None:
    ambiguous = verified_claim_line(
        "Сторона обязана передать товар в согласованный договором срок.",
        "статья 699 ГК РК (Особенная часть)",
        ARTICLE_700_SHARED,
        GK_SPECIAL_URL,
    )
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(ambiguous), draft)

    assert not draft.legal_basis
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert not any(note.startswith("LEGAL_CORRECTION:") for note in _research(ambiguous).notes)


def test_both_companies_route_to_almaty_economic_court(grounding_corpus: Path) -> None:
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(_valid_service_claim()), draft)

    assert draft.court == "Специализированный межрайонный экономический суд города Алматы"


def test_company_vs_ordinary_person_is_not_forced_into_economic_court(grounding_corpus: Path) -> None:
    draft = _draft(mixed=True)

    finalize_professional_claim(_case_context(mixed=True), _research(_valid_service_claim()), draft)

    assert "экономическ" not in draft.court.lower()


def test_administrative_dispute_between_legal_entities_keeps_special_court(grounding_corpus: Path) -> None:
    draft = _draft()
    draft.defendant = ["ГУ «Управление контроля»", "БИН 990140001122", "Адрес: г. Алматы"]
    draft.court = "Специализированный межрайонный административный суд города Алматы"
    context = (
        "Истец: ТОО «Альфа Строй», БИН 190440012345, г. Алматы.\n"
        "Ответчик: ГУ «Управление контроля», БИН 990140001122, г. Алматы.\n"
        "Административный иск об оспаривании решения государственного органа."
    )

    finalize_professional_claim(context, _research(_valid_service_claim()), draft)

    assert "административный" in draft.court.lower()
    assert "экономическ" not in draft.court.lower()


def test_legal_entity_filing_requirements_are_notes_not_fabricated_attachments(grounding_corpus: Path) -> None:
    draft = _draft()
    original = list(draft.attachments)

    finalize_professional_claim(_case_context(), _research(_valid_service_claim()), draft)

    assert draft.attachments == original
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    notes = "\n".join(draft.verification_notes).lower()
    assert "банковские реквизиты" in notes
    assert "государственной пошлины" in notes
    assert "регистрации/перерегистрации" in notes
    assert all(note.startswith((FILING_ACTION_PREFIX, LEGAL_GROUNDING_PREFIX)) for note in draft.verification_notes)


def test_supplied_bank_and_filing_documents_clear_corresponding_actions(grounding_corpus: Path) -> None:
    draft = _draft()
    draft.attachments.extend([
        "Платежное поручение об уплате государственной пошлины 54 000 тенге",
        "Справка о государственной регистрации юридического лица",
    ])

    finalize_professional_claim(_case_context(with_bank=True), _research(_valid_service_claim()), draft)

    notes = "\n".join(draft.verification_notes).lower()
    assert "банковские реквизиты" not in notes
    assert "государственной пошлины" not in notes
    assert "регистрации/перерегистрации" not in notes
    assert draft.status == VerificationStatus.VERIFIED


def test_disabled_local_corpus_fails_closed_without_filing_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(_valid_service_claim()), draft)

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert draft.legal_basis == []
    assert any(note.startswith(LEGAL_GROUNDING_PREFIX) for note in draft.verification_notes)


def test_internal_verification_marker_never_reaches_claim_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KORGAN_LOCAL_CORPUS", raising=False)
    marker_claim = verified_claim_line(
        "[ТРЕБУЕТ ПРОВЕРКИ: содержание нормы] Заказчик обязан оплатить услуги.",
        "статья 685 ГК РК (Особенная часть)",
        ARTICLE_685,
        GK_SPECIAL_URL,
    )
    draft = _draft()

    finalize_professional_claim(_case_context(), _research(marker_claim), draft)
    doc = Document(BytesIO(build_claim_docx(draft)))
    visible = "\n".join(paragraph.text for paragraph in doc.paragraphs)

    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert not draft.legal_basis
    assert "[ТРЕБУЕТ ПРОВЕРКИ" not in visible
    assert ".." not in visible
