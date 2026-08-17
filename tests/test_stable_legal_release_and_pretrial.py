from __future__ import annotations

import io

from docx import Document

from korgan.legal.corpus import ACT_LABOR, KNOWN_ACTS
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, build_pretrial_docx, is_pretrial_request
from korgan.stable_legal_release import (
    clean_language_labels,
    normalize_claim_legal_basis,
    sanitize_research_sources,
)


def _research(lines: list[str], urls: list[str] | None = None) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=lines,
        unverified_claims=[],
        source_urls=urls or [],
        notes=[],
    )


def _verified(statement: str, article: str, text: str, url: str) -> str:
    return f"{statement} [основание: {article}; текст нормы: «{text}»; источник: {url}]"


def test_labor_code_is_in_local_corpus_allowlist() -> None:
    assert ACT_LABOR == "TK_RK"
    assert KNOWN_ACTS[ACT_LABOR][0] == "K1500000414"


def test_language_version_labels_are_removed_from_filing_text() -> None:
    raw = "Правовое основание: статья 96 ТК РК (английская версия), в системной связи с англ. ст. 96 ТК РК"
    cleaned = clean_language_labels(raw)
    assert "англий" not in cleaned.lower()
    assert "англ." not in cleaned.lower()
    assert "русск" not in cleaned.lower()


def test_english_adilet_translation_is_not_verified_source() -> None:
    rus = _verified(
        "При прекращении трудового договора выплачивается компенсация за неиспользованный отпуск",
        "статья 96 ТК РК",
        "При прекращении трудового договора работнику, который не использовал отпуск, производится компенсационная выплата.",
        "https://adilet.zan.kz/rus/docs/K1500000414",
    )
    eng = _verified(
        "Компенсация за отпуск (английская версия)",
        "статья 96 ТК РК (английская версия)",
        "Upon termination of the employment contract an employee shall be compensated.",
        "https://adilet.zan.kz/eng/docs/K1500000414",
    )
    research = _research(
        [rus, eng],
        ["https://adilet.zan.kz/rus/docs/K1500000414", "https://adilet.zan.kz/eng/docs/K1500000414"],
    )
    sanitize_research_sources(research)
    assert len(research.verified_claims) == 1
    assert "/eng/" not in "\n".join(research.verified_claims)
    assert all("/eng/" not in url for url in research.source_urls)


def test_employment_claim_gets_separate_salary_leave_and_immediate_execution_basis() -> None:
    research = _research(
        [
            _verified(
                "Работодатель обязан выплатить задолженность по заработной плате",
                "статья 113 ТК РК",
                "При невыплате заработной платы работодатель выплачивает работнику задолженность и пеню за период задержки платежа.",
                "https://adilet.zan.kz/rus/docs/K1500000414",
            ),
            _verified(
                "При прекращении трудового договора выплачивается компенсация за неиспользованный отпуск",
                "статья 96 ТК РК",
                "При прекращении трудового договора работнику производится компенсационная выплата за неиспользованные дни отпуска.",
                "https://adilet.zan.kz/rus/docs/K1500000414",
            ),
            _verified(
                "Решение о присуждении работнику заработной платы подлежит немедленному исполнению в пределах трех месяцев",
                "статья 243 ГПК РК",
                "Немедленному исполнению подлежат решения о присуждении работнику заработной платы, но не свыше чем за три месяца.",
                "https://adilet.zan.kz/rus/docs/K1500000377",
            ),
        ]
    )
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск о взыскании заработной платы",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="680 000 ₸",
        facts=["Работодатель не выплатил зарплату и компенсацию за отпуск."],
        legal_basis=[
            "При прекращении трудового договора выплачивается компенсация. Правовое основание: статья 96 ТК РК (русская редакция).",
            "Компенсация рассчитывается из средней зарплаты. Правовое основание: статья 96 ТК РК (английская версия).",
        ],
        requests=[
            "Взыскать задолженность по заработной плате 420 000 тенге.",
            "Взыскать компенсацию за неиспользованный отпуск 260 000 тенге.",
            "Обратить решение о взыскании заработной платы к немедленному исполнению.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )
    missing = normalize_claim_legal_basis(draft, research)
    text = "\n".join(draft.legal_basis)
    assert missing == []
    assert "статья 113" in text
    assert "статья 96" in text
    assert "статья 243" in text
    assert text.lower().count("статья 96") == 1
    assert "англий" not in text.lower()
    assert "русск" not in text.lower()


def test_salary_without_verified_basis_is_not_release_ready() -> None:
    research = _research([])
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="420 000 ₸",
        facts=["Зарплата не выплачена."],
        legal_basis=[],
        requests=["Взыскать задолженность по заработной плате 420 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )
    missing = normalize_claim_legal_basis(draft, research)
    assert "взыскание заработной платы" in missing
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION


def test_pretrial_intent_is_action_only_not_advice() -> None:
    assert is_pretrial_request("Подготовь досудебную претензию о возврате денег")
    assert is_pretrial_request("Сотқа дейінгі талапты дайында")
    assert is_pretrial_request("Сотқа дейінгі талапқа мәтін әзірле")
    assert not is_pretrial_request("Как составить досудебную претензию?")
    assert not is_pretrial_request("Сотқа дейінгі талапты қалай дайындауға болады?")


def test_pretrial_docx_is_professional_and_has_separate_attachment_numbering() -> None:
    draft = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["Иванов И.И."],
        recipient=["ТОО Ромашка"],
        facts=["Оплата произведена, обязательство не исполнено."],
        legal_basis=["Обязательство подлежит исполнению. Правовое основание: статья 272 ГК РК."],
        demands=["Вернуть 100 000 тенге.", "Предоставить письменный ответ."],
        deadline="в срок, установленный законом или договором",
        consequences=["При неисполнении заявитель вправе обратиться за судебной защитой."],
        attachments=["Копия договора", "Копия платежного документа"],
    )
    data = build_pretrial_docx(draft, language="ru")
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ДОСУДЕБНАЯ ПРЕТЕНЗИЯ" in text
    assert "ТРЕБУЮ:" in text
    assert "1. Вернуть 100 000 тенге." in text
    assert "1. Копия договора" in text
    assert "английская версия" not in text.lower()
