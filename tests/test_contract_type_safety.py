"""Сайт и мобильное приложение — не проектно-изыскательские работы.

Параграф ГК РК о подряде на проектные и изыскательские работы написан про
проектную документацию и изыскания для строительства: там свои правила о
задании на проектирование, согласовании документации и ответственности за
недостатки проекта. Разработка сайта или мобильного приложения под них не
подпадает, а «строительный подряд» тем более.

Ошибка соблазнительна: и там и там есть заказчик, подрядчик, техническое
задание и этапы сдачи. Но если документ выбирает этот параграф, весь раздел
правового обоснования говорит не о том договоре, который стороны заключили, —
и оппоненту достаточно одного абзаца, чтобы это показать.

Правило: пока в материалах нет строительства, классификация «проектные и
изыскательские работы» либо «строительный подряд» блокирует выпуск документа.
"""

from __future__ import annotations

from korgan.contract_type_safety import misclassification_blockers
from korgan.document_quality import assess_document_quality
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


WEBSITE_CONTEXT = (
    "Истец: ТОО «KAZTECH SOLUTIONS», БИН 230740012345.\n"
    "Ответчик: ТОО «WEB STUDIO KZ», БИН 200140012345.\n"
    "10.01.2026 заключен договор на разработку корпоративного сайта. "
    "Оплачено 1 500 000 тенге, сайт в срок не сдан."
)

APP_CONTEXT = (
    "Заказчик: ТОО «KAZTECH SOLUTIONS», БИН 230740012345.\n"
    "Исполнитель: ТОО «MOBILE LAB», БИН 200140067891.\n"
    "Предмет: разработка мобильного приложения для iOS и Android."
)

BUILDING_CONTEXT = (
    "Заказчик: ТОО «KAZTECH SOLUTIONS», БИН 230740012345.\n"
    "Подрядчик: ТОО «PROJECT INSTITUTE», БИН 200140067891.\n"
    "Предмет: разработка проектной документации на строительство жилого дома "
    "и инженерные изыскания на площадке."
)


def _claim(*, legal_basis: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании уплаченной суммы",
        court="СМЭС города Астаны",
        claimant=["ТОО «KAZTECH SOLUTIONS», БИН 230740012345"],
        defendant=["ТОО «WEB STUDIO KZ», БИН 200140012345"],
        price_of_claim="1 500 000 тенге",
        state_duty="45 000 тенге",
        facts=["Ответчик не сдал сайт в согласованный срок."],
        legal_basis=legal_basis,
        requests=["Взыскать уплаченную сумму 1 500 000 тенге."],
        attachments=["Договор от 10.01.2026", "Платежное поручение"],
        verification_notes=[],
        source_urls=[],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        notes=[],
        source_urls=[],
    )


# --- квалификация предмета ---


def test_website_development_is_not_design_and_survey_work() -> None:
    lines = ["К отношениям сторон применяются правила о подряде на проектные и изыскательские работы."]

    assert misclassification_blockers(WEBSITE_CONTEXT, lines)


def test_mobile_application_is_not_construction_contracting() -> None:
    lines = ["Договор является договором строительного подряда."]

    assert misclassification_blockers(APP_CONTEXT, lines)


def test_survey_work_wording_alone_is_enough_to_block() -> None:
    lines = ["Ответчик не выполнил изыскательские работы в согласованный срок."]

    assert misclassification_blockers(APP_CONTEXT, lines)


def test_real_construction_project_keeps_its_own_classification() -> None:
    lines = ["К отношениям применяются правила о подряде на проектные и изыскательские работы."]

    assert misclassification_blockers(BUILDING_CONTEXT, lines) == []


def test_ordinary_work_contract_classification_is_not_blocked() -> None:
    lines = [
        "К отношениям сторон применяются правила о договоре подряда: подрядчик обязан "
        "выполнить работу в согласованный срок."
    ]

    assert misclassification_blockers(WEBSITE_CONTEXT, lines) == []


def test_paid_services_classification_is_not_blocked() -> None:
    lines = ["Отношения сторон являются возмездным оказанием услуг."]

    assert misclassification_blockers(APP_CONTEXT, lines) == []


# --- шлюз качества ---


def test_quality_gate_blocks_a_misclassified_website_claim() -> None:
    draft = _claim(
        legal_basis=[
            "К отношениям сторон применяются правила о подряде на проектные и изыскательские работы."
        ]
    )

    report = assess_document_quality("claim", WEBSITE_CONTEXT, _research(), draft)

    assert report.ready is False
    assert any("изыскательск" in blocker.lower() for blocker in report.hard_blockers)


def test_quality_gate_does_not_block_a_correctly_classified_website_claim() -> None:
    draft = _claim(legal_basis=["Подрядчик обязан выполнить работу в согласованный договором срок."])

    report = assess_document_quality("claim", WEBSITE_CONTEXT, _research(), draft)

    assert not any("изыскательск" in blocker.lower() for blocker in report.hard_blockers)
