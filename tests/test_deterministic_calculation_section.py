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

from dataclasses import replace

from korgan import late_interest_hotfix
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


def test_contractual_penalty_after_a_partial_payment_is_charged_on_the_balance() -> None:
    """Платёж середины периода уменьшает базу, а не остаётся незамеченным.

    Одной формулой вышло бы 12 000 000 × 0,1% × 85 дн. = 1 020 000 — начисление
    на весь долг и после того, как треть его вернули. По остатку:
    12 000 000 × 0,1% × 31 дн. = 372 000, затем 8 000 000 × 0,1% × 54 дн. = 432 000.
    """
    draft = _supply_draft()
    context = CONTRACT_CONTEXT + (
        "01.07.2026 ответчик частично оплатил задолженность в размере 4 000 000 тенге.\n"
    )

    _apply_verified_penalty(context, _supply_research(), draft, filing_date=date(2026, 8, 23))

    body = "\n".join(draft.calculation)
    assert "1 020 000" not in body
    assert "Договорная неустойка: 804 000 тенге" in body
    assert "31.05.2026—30.06.2026: 12 000 000 тенге × 0,1% × 31 дн. = 372 000 тенге" in body
    assert "01.07.2026—23.08.2026: 8 000 000 тенге × 0,1% × 54 дн. = 432 000 тенге" in body
    assert any("804 000 тенге" in item for item in draft.requests)
    assert not any("1 020 000" in item for item in draft.requests)


def test_a_penalty_that_disagrees_with_the_document_is_withdrawn_not_patched() -> None:
    """Расхождение сумм снимает требование, а не подставляет «правильное» число.

    Строка неустойки, таблица расчёта и просительная часть переписываются
    разными ветками кода. Если они разошлись, неизвестно, какая часть документа
    устарела, — поэтому требование уходит юристу целиком.
    """
    from decimal import Decimal

    from korgan.late_interest_hotfix import _enforce_calculation_gate
    from korgan.penalty_engine import PenaltyTerms, RateType, calculate_penalty

    calculation = calculate_penalty(
        12_000_000,
        date(2026, 5, 31),
        date(2026, 8, 23),
        PenaltyTerms(
            rate=Decimal("0.1"),
            rate_type=RateType.PER_DAY,
            contract_basis="пункт 6.3 договора",
            rate_source="пункт 6.3 договора",
        ),
    )
    assert calculation.total == 1_020_000

    draft = _supply_draft()
    draft.late_interest = "1 020 000 тенге"
    draft.calculation = [
        "Основной долг: 12 000 000 тенге.",
        "Договорная неустойка: 1 020 000 тенге.",
        "Итого цена иска: 13 020 000 тенге.",
    ]
    # В просительной части осталась прежняя сумма модели.
    draft.requests = [
        "Взыскать основной долг 12 000 000 тенге.",
        "Взыскать договорную неустойку по пункту 6.3 договора в размере 996 000 тенге.",
    ]

    _enforce_calculation_gate(
        draft, calculation, principal=12_000_000, case_context=CONTRACT_CONTEXT
    )

    assert "1 020 000" not in " ".join(draft.requests)
    assert not any("996 000" in item for item in draft.requests)
    assert any("не сошёлся с текстом документа" in note for note in draft.verification_notes)

    # Разбор расхождения адресован юристу и называет суммы читаемо. В самой
    # просительной части его быть не должно: перечисленные там чужие суммы
    # читаются как заявленное требование.
    detail = " ".join(draft.verification_notes)
    assert "996 000 тенге" in detail and "1 020 000 тенге" in detail
    assert not any("Расхождения:" in item for item in draft.requests)


def test_the_gate_also_guards_the_single_period_path(monkeypatch) -> None:
    """Гейт закрывает и обычное дело, а не только погашение частями.

    Долг, погашавшийся частями, считается по интервалам, и там сверка стояла
    с самого начала. Но большинство исков — один период и одна формула, и до
    сих пор эта ветка писала расчёт в документ вообще без сверки: ошибиться
    она могла ровно так же, а поймать её было нечем.

    Здесь исторический калькулятор подменён на возвращающий чужое число.
    Документ пишется из него, эталон движка остаётся настоящим — и требование
    обязано уйти юристу, а не в суд с непроверенной суммой.
    """
    real = late_interest_hotfix.calc_contractual_penalty

    def wrong(principal, terms, start, end):
        honest = real(principal, terms, start, end)
        return replace(honest, amount=honest.amount + 24_000)

    monkeypatch.setattr(late_interest_hotfix, "calc_contractual_penalty", wrong)

    draft = _supply_draft()
    _apply_verified_penalty(CONTRACT_CONTEXT, _supply_research(), draft, filing_date=date(2026, 8, 23))

    assert draft.status is VerificationStatus.NEEDS_VERIFICATION
    assert any("не сошёлся с текстом документа" in note for note in draft.verification_notes)
    # Сумма расхождения не попадает в просительную часть ни в каком виде:
    # ни «правильная», ни та, что калькулятор насчитал.
    assert not any("1 044 000" in item for item in draft.requests)
    assert not any("1 020 000" in item for item in draft.requests)


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
