"""Раздел «Расчёт взыскиваемых сумм» принадлежит детерминированной арифметике.

Модуль ``late_interest_hotfix`` пересчитывает неустойку, переписывает просительную
часть, цену иска и госпошлину — но исторически не трогал ``draft.calculation``.
В документ попадал расчёт, написанный моделью: с прежней суммой неустойки,
прежним итогом и прежней ставкой. Юрист видел два разных числа в одном иске.

Здесь фиксируется обратное правило: если детерминированный расчёт выполнен, он
и есть содержание раздела; если он не выполнен, раздел не вправе утверждать
неустойку, которой в просительной части больше нет.
"""

from __future__ import annotations

from datetime import date

from korgan.claim_consistency_guard import claim_consistency_errors
from korgan.late_interest_hotfix import _apply_verified_penalty
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


CONTRACT_CONTEXT = """
Истец: ТОО «KAZTECH SOLUTIONS», БИН 230740012345
Ответчик: ТОО «ASTANA INDUSTRY GROUP», БИН 210940067891
15.05.2026 заключен договор поставки № KT-15/05-26. 20.05.2026 поставлен товар
на 12 000 000 тенге. Пункт 3.2: оплата в течение 10 календарных дней.
Срок оплаты истек 30.05.2026.
Пункт 6.3 договора: неустойка 0,1% от суммы задолженности за каждый день
просрочки, но не более 10% от суммы задолженности.
Прошу взыскать основной долг и договорную неустойку с 31.05.2026.
"""


def _supply_draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности и договорной неустойки по договору поставки",
        court="СМЭС города Астаны",
        claimant=["ТОО «KAZTECH SOLUTIONS»"],
        defendant=["ТОО «ASTANA INDUSTRY GROUP»"],
        price_of_claim="12 996 000 тенге",
        facts=["Задолженность 12 000 000 тенге основного долга и 996 000 тенге неустойки."],
        legal_basis=["Обязанность покупателя оплатить принятый товар."],
        requests=[
            "Взыскать основной долг 12 000 000 тенге.",
            "Взыскать договорную неустойку по пункту 6.3 договора в размере 996 000 тенге.",
            "Взыскать расходы по уплате государственной пошлины.",
        ],
        attachments=["Расчет договорной неустойки на 996 000 тенге."],
        verification_notes=[],
        source_urls=[],
    )


def _supply_research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["ГК РК (Особенная часть), договор поставки"],
        procedural_requirements=[],
        verified_claims=["Покупатель обязан оплатить принятый товар."],
        unverified_claims=[],
        notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )


def _loan_draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании долга и неустойки",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Истец Тестов, ИИН 900000000001"],
        defendant=["Ответчик Примеров"],
        price_of_claim="800 000 тенге",
        facts=[],
        legal_basis=["Модель написала проценты по денежному обязательству."],
        requests=[
            "Взыскать основной долг 800 000 тенге.",
            "Взыскать неустойку за просрочку денежного обязательства.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _verified_353() -> LegalResearch:
    url = "https://adilet.zan.kz/rus/docs/K940001000_/compare"
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[f"Статья 353 применима к просрочке [основание: 353; источник: {url}]"],
        unverified_claims=[],
        source_urls=[url],
        notes=[],
    )


LOAN_CONTEXT = (
    "Истец ИИН 900000000001. Ответчик обязался вернуть сумму не позднее 10 апреля 2026 года. "
    "Прошу взыскать неустойку по статье 353 ГК РК за просрочку."
)


# --- договорная неустойка ---


def test_contractual_penalty_writes_the_calculation_section() -> None:
    """Раздел расчёта раскрывает базу, ставку, период и дни, а не только итог."""
    draft = _supply_draft()
    _apply_verified_penalty(CONTRACT_CONTEXT, _supply_research(), draft, filing_date=date(2026, 8, 23))

    body = "\n".join(draft.calculation)
    assert "Основной долг: 12 000 000 тенге" in body
    assert "Договорная неустойка: 1 020 000 тенге" in body
    assert "база: 12 000 000 тенге" in body
    assert "ставка: 0,1% за каждый день просрочки".replace(",", ".") in body.replace(",", ".")
    assert "дней: 85" in body
    assert "Итого цена иска: 13 020 000 тенге." in body


def test_stale_model_calculation_is_replaced_by_deterministic_arithmetic() -> None:
    """Модель посчитала 996 000; детерминированный расчёт даёт 1 020 000."""
    draft = _supply_draft()
    draft.calculation = [
        "Основной долг: 12 000 000 тенге.",
        "Договорная неустойка: 996 000 тенге.",
        "Итого цена иска: 12 996 000 тенге.",
    ]

    _apply_verified_penalty(CONTRACT_CONTEXT, _supply_research(), draft, filing_date=date(2026, 8, 23))

    body = "\n".join(draft.calculation)
    assert "996 000" not in body
    assert "12 996 000" not in body
    assert "1 020 000 тенге" in body


def test_calculated_claim_passes_the_calculation_to_prayer_reconciliation() -> None:
    """Сверка расчёта с просительной частью не должна блокировать собственный расчёт."""
    draft = _supply_draft()
    _apply_verified_penalty(CONTRACT_CONTEXT, _supply_research(), draft, filing_date=date(2026, 8, 23))

    errors = claim_consistency_errors(CONTRACT_CONTEXT, draft)

    assert not any("ПРОШУ СУД" in error and "неустойк" in error.lower() for error in errors)


# --- статья 353 ГК РК ---


def test_article_353_penalty_writes_the_calculation_section() -> None:
    draft = _loan_draft()
    _apply_verified_penalty(LOAN_CONTEXT, _verified_353(), draft, filing_date=date(2026, 8, 16))

    body = "\n".join(draft.calculation)
    assert "Основной долг: 800 000 тенге" in body
    assert "46 992 тенге" in body
    assert "353" in body
    assert "дней: 128" in body
    assert "Итого цена иска: 846 992 тенге." in body


# --- fail-closed ---


def test_unrequested_penalty_cannot_survive_in_the_calculation_section() -> None:
    """Неустойку никто не заявлял: раздел расчёта не вправе её удерживать."""
    draft = _loan_draft()
    draft.requests = ["Взыскать основной долг 800 000 тенге."]
    draft.calculation = [
        "Основной долг: 800 000 тенге.",
        "Неустойка: 46 992 тенге.",
        "Итого цена иска: 846 992 тенге.",
    ]
    context = "Истец ИИН 900000000001. Неустойка договором не предусмотрена. Проценты не заявляю."

    _apply_verified_penalty(context, _verified_353(), draft, filing_date=date(2026, 8, 16))

    body = "\n".join(draft.calculation)
    assert "46 992" not in body
    assert "846 992" not in body


def test_unverified_penalty_leaves_no_calculated_penalty_amount() -> None:
    """Ставка не установлена и статья 353 не подтверждена — числа в расчёте нет."""
    draft = _loan_draft()
    draft.calculation = [
        "Основной долг: 800 000 тенге.",
        "Неустойка: 46 992 тенге.",
        "Итого цена иска: 846 992 тенге.",
    ]
    research = LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )

    _apply_verified_penalty(LOAN_CONTEXT, research, draft, filing_date=date(2026, 8, 16))

    body = "\n".join(draft.calculation)
    assert "46 992" not in body
    assert "846 992" not in body
