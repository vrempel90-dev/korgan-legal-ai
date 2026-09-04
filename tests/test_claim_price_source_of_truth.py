"""ARCH-002: цена иска считается по структурированным имущественным требованиям.

Раньше ``_recalculate_price`` складывала все денежные суммы, найденные в готовом
тексте просительной части. Из-за этого в цену имущественного иска попадала
компенсация морального вреда, операнды формулы складывались с её же
результатом, а повторённое «итого» удваивало сумму. Любая из этих ошибок молча
превращалась в «детерминированную» госпошлину.

Здесь зафиксировано новое поведение: единственный источник истины —
``korgan.claim_price``; когда сумму нельзя установить достоверно, цена иска не
угадывается, а обнуляется, и госпошлина остаётся нерассчитанной.
"""

from __future__ import annotations

import asyncio
import re

from korgan.claim_price import (
    MIXED_CLAIM_NOTE,
    PRICE_UNRESOLVED_NOTE_PREFIX,
    ClaimPriceStatus,
    ComponentRole,
    resolve_claim_price,
)
from korgan.config import Settings
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.legal_calc import NEEDS_CALCULATION_MARKER, gosposhlina_line
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.production_legal import STATE_DUTY_NOTE
from korgan.professional_claim_finalizer import _apply_claim_price

CASE_CONTEXT = (
    "Истец: Сериков Арман Нурланович, ИИН 000000000001, дата рождения 03.02.1990, "
    "адрес: город Алматы, Бостандыкский район, улица Тестовая, дом 25, квартира 18.\n"
    "Ответчик: ТОО «Мебель Стандарт», БИН 000000000002, "
    "адрес: город Алматы, Алмалинский район, улица Условная, дом 50.\n"
    "Истец оплатил 1 200 000 тенге по договору № MS-114/26, кухня не изготовлена."
)

# Строка цены иска, которую детерминированно формирует расчёт статьи 353 ГК РК.
ARTICLE_353_PRICE = (
    "1 293 600 тенге (основной долг 1 200 000 тенге + неустойка по статье 353 ГК РК "
    "93 600 тенге на дату подачи иска)"
)


def _draft(requests: list[str], price: str = "1 200 000 тенге") -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании предварительной оплаты",
        court="Бостандыкский районный суд города Алматы",
        claimant=["Сериков Арман Нурланович, ИИН 000000000001"],
        defendant=["ТОО «Мебель Стандарт», БИН 000000000002"],
        price_of_claim=price,
        facts=["Ответчик не изготовил и не установил кухонный гарнитур."],
        legal_basis=[],
        requests=list(requests),
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _price_note(draft: ClaimDraft) -> str:
    notes = [note for note in draft.verification_notes if note.startswith(PRICE_UNRESOLVED_NOTE_PREFIX)]
    assert len(notes) == 1, draft.verification_notes
    return notes[0]


def _duty(draft: ClaimDraft) -> str:
    return gosposhlina_line(CASE_CONTEXT, draft.price_of_claim)


# --------------------------------------------------------------------------
# A. Моральный вред — неимущественное требование и в цену иска не входит.
# --------------------------------------------------------------------------


def test_moral_damage_is_not_added_to_the_price_of_a_pecuniary_claim() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты по договору № MS-114/26.",
        "Взыскать с ответчика в пользу истца компенсацию морального вреда в размере 300 000 тенге.",
    ])

    _apply_claim_price(draft)

    # 1 500 000 — прежний неверный результат сложения двух разнородных требований.
    assert draft.price_of_claim == "1 200 000 тенге"
    assert _duty(draft).startswith("12 000 тенге")
    # Неимущественное требование остаётся в иске, но пошлина по нему считается отдельно.
    assert MIXED_CLAIM_NOTE in draft.verification_notes


def test_claim_with_only_a_moral_demand_has_no_pecuniary_price() -> None:
    draft = _draft(
        ["Взыскать с ответчика в пользу истца компенсацию морального вреда в размере 300 000 тенге."],
        price="300 000 тенге",
    )

    _apply_claim_price(draft)

    assert draft.price_of_claim == ""
    assert _duty(draft) == NEEDS_CALCULATION_MARKER
    assert "неимущественное денежное требование" in _price_note(draft)


# --------------------------------------------------------------------------
# B. Операнды формулы не складываются с её результатом.
# --------------------------------------------------------------------------


def test_formula_operands_are_never_added_to_the_formula_result() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты.",
        "Взыскать неустойку по договору: 1 200 000 тенге × 0,1% × 78 дн. = 93 600 тенге.",
    ])

    _apply_claim_price(draft)

    # Прежний результат: 1 200 000 + 1 200 000 + 93 600 = 2 493 600 тенге.
    assert draft.price_of_claim == ""
    assert _duty(draft) == NEEDS_CALCULATION_MARKER
    assert "несколько сумм" in _price_note(draft)


# --------------------------------------------------------------------------
# C. Повторённое «итого» не удваивает сумму.
# --------------------------------------------------------------------------


def test_inline_total_does_not_double_the_price() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга "
        "и 93 600 тенге неустойки, итого 1 293 600 тенге.",
    ])

    _apply_claim_price(draft)

    # Прежний результат: 1 200 000 + 93 600 + 1 293 600 = 2 587 200 тенге.
    assert draft.price_of_claim == ""
    assert _duty(draft) == NEEDS_CALCULATION_MARKER


def test_separate_matching_total_is_a_checksum_not_an_extra_component() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга.",
        "Взыскать с ответчика в пользу истца 93 600 тенге неустойки по договору.",
        "Итого взыскать с ответчика в пользу истца 1 293 600 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == "1 293 600 тенге"
    assert _duty(draft).startswith("12 936 тенге")
    assert draft.verification_notes == []


def test_total_that_contradicts_the_components_fails_closed() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга.",
        "Взыскать с ответчика в пользу истца 93 600 тенге неустойки по договору.",
        "Итого взыскать с ответчика в пользу истца 1 500 000 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == ""
    assert _duty(draft) == NEEDS_CALCULATION_MARKER
    assert "не совпадает" in _price_note(draft)


# --------------------------------------------------------------------------
# D. Детерминированно рассчитанная цена не перезаписывается.
# --------------------------------------------------------------------------


def test_deterministic_article_353_price_survives_the_finalizer() -> None:
    draft = _draft(
        [
            "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга.",
            "Взыскать с ответчика в пользу истца неустойку по статье 353 ГК РК в размере 93 600 тенге "
            "за период с 16.06.2026 по 31.08.2026 исходя из базовой ставки НБ РК 16,5% "
            "на дату предъявления иска; за последующий период — по день фактической уплаты суммы долга.",
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины "
            "в размере 12 936 тенге.",
        ],
        price=ARTICLE_353_PRICE,
    )

    _apply_claim_price(draft)

    # Расшифровка «основной долг + неустойка» сохранена целиком.
    assert draft.price_of_claim == ARTICLE_353_PRICE
    assert _duty(draft).startswith("12 936 тенге")
    assert draft.verification_notes == []


# --------------------------------------------------------------------------
# Сохранение существующих корректных сценариев.
# --------------------------------------------------------------------------


def test_wrong_model_price_is_still_corrected_from_the_components() -> None:
    draft = _draft(
        ["Взыскать с ответчика в пользу истца 2 300 000 тенге предварительной оплаты."],
        price="2 500 000 тенге",
    )

    _apply_claim_price(draft)

    assert draft.price_of_claim == "2 300 000 тенге"


def test_price_is_untouched_when_the_prayer_claims_no_money() -> None:
    draft = _draft(
        ["Обязать ответчика передать истцу изготовленный кухонный гарнитур."],
        price="1 200 000 тенге",
    )

    _apply_claim_price(draft)

    assert draft.price_of_claim == "1 200 000 тенге"
    assert draft.verification_notes == []


def test_duty_costs_and_alternative_demands_stay_out_of_the_price() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты.",
        "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере 12 000 тенге.",
        "Взыскать с ответчика в пользу истца судебные расходы в размере 150 000 тенге.",
        "В порядке альтернативного требования расторгнуть договор и взыскать 1 200 000 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == "1 200 000 тенге"


def test_unresolved_price_invalidates_a_previously_computed_duty() -> None:
    """Число пошлины не должно пережить обнуление цены иска даже без вызова _apply_state_duty."""
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты "
        "и убытки в размере 350 000 тенге.",
    ])
    draft.state_duty = "15 500 тенге (1% от цены иска)"

    _apply_claim_price(draft)

    assert draft.price_of_claim == ""
    assert draft.state_duty == NEEDS_CALCULATION_MARKER


def test_finalizer_notes_are_not_duplicated_on_the_second_pass() -> None:
    """Продакшн-путь вызывает финалайзер дважды подряд."""
    draft = _draft([
        "Взыскать неустойку по договору: 1 200 000 тенге × 0,1% × 78 дн. = 93 600 тенге.",
        "Взыскать с ответчика в пользу истца компенсацию морального вреда в размере 300 000 тенге.",
    ])

    _apply_claim_price(draft)
    _apply_claim_price(draft)

    assert draft.verification_notes.count(MIXED_CLAIM_NOTE) == 1
    assert len([n for n in draft.verification_notes if n.startswith(PRICE_UNRESOLVED_NOTE_PREFIX)]) == 1


# --------------------------------------------------------------------------
# Классификация структурированных компонентов.
# --------------------------------------------------------------------------


def test_resolver_classifies_each_demand_by_role() -> None:
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты.",
        "Взыскать с ответчика в пользу истца компенсацию морального вреда в размере 300 000 тенге.",
        "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере 12 000 тенге.",
        "Обязать ответчика возвратить истцу проектную документацию.",
    ])

    price = resolve_claim_price(draft)

    assert price.status is ClaimPriceStatus.RESOLVED
    assert price.total == 1_200_000
    assert [item.role for item in price.components] == [
        ComponentRole.PECUNIARY,
        ComponentRole.NON_PECUNIARY,
        ComponentRole.PROCEDURAL,
        ComponentRole.NON_MONETARY,
    ]
    assert [item.amount for item in price.pecuniary_components()] == [1_200_000]
    assert price.has_non_pecuniary_money() is True


def test_resolver_reports_the_reason_instead_of_a_number() -> None:
    draft = _draft(["Взыскать 1 200 000 тенге долга и 93 600 тенге неустойки, итого 1 293 600 тенге."])

    price = resolve_claim_price(draft)

    assert price.status is ClaimPriceStatus.AMBIGUOUS
    assert price.total is None
    assert price.reason


def test_resolver_reports_absence_of_monetary_relief_separately_from_ambiguity() -> None:
    draft = _draft(["Обязать ответчика передать истцу изготовленный кухонный гарнитур."])

    price = resolve_claim_price(draft)

    assert price.status is ClaimPriceStatus.NO_MONETARY_RELIEF
    assert price.total is None


# --------------------------------------------------------------------------
# Продакшн-путь: неоднозначная цена иска не превращается в число госпошлины.
# --------------------------------------------------------------------------

_E2E_CONTEXT = (
    "Истец: Сериков Арман Нурланович, ИИН 000000000001, "
    "адрес: город Алматы, Бостандыкский район, улица Тестовая, дом 25, квартира 18.\n"
    "Ответчик: ТОО «Мебель Стандарт», БИН 000000000002, "
    "адрес: город Алматы, Алмалинский район, улица Условная, дом 50.\n"
    "Кухонный гарнитур по договору № MS-114/26 не изготовлен и не установлен."
)

_E2E_RESEARCH = LegalResearch(
    status=VerificationStatus.NEEDS_VERIFICATION,
    applicable_law=[],
    procedural_requirements=[],
    verified_claims=[],
    unverified_claims=[],
    source_urls=[],
    notes=[],
)


class _FakeFinalizedService(FinalizedProductionClaimService):
    """Рантайм без сети: ответы Responses API задаёт тест."""

    def __init__(self, claim: dict) -> None:
        super().__init__(Settings(telegram_bot_token="test", openai_api_key="test"))
        self._claim = claim

    async def _structured_response(self, *, model, instructions, content, schema_name, schema, tools=None):
        if "validation" in schema_name:
            return {"critical_errors": [], "unsupported_legal_claims": [], "missing_required_fields": []}, None
        return dict(self._claim), None


def _model_claim(*, price: str, requests: list[str]) -> dict:
    return {
        "title": "ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании предварительной оплаты",
        "court": "[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]",
        "claimant": ["Сериков Арман Нурланович, ИИН 000000000001"],
        "defendant": ["ТОО «Мебель Стандарт», БИН 000000000002"],
        "price_of_claim": price,
        "facts": ["Ответчик не изготовил и не установил кухонный гарнитур по договору № MS-114/26."],
        "legal_basis": ["Подрядчик обязан выполнить работу в согласованный договором срок."],
        "requests": list(requests),
        "attachments": ["Копия договора № MS-114/26"],
        "verification_notes": [],
    }


def test_production_path_never_turns_an_ambiguous_price_into_a_duty_number() -> None:
    """Сквозной сценарий требования 10 ARCH-002.

    Требование содержит две суммы, поэтому цена иска структурно не определяется.
    Прежний код складывал их (1 200 000 + 350 000) и выдавал госпошлину
    15 500 тенге как достоверную. Теперь цена иска обнуляется, и пошлина
    остаётся нерассчитанной по всей цепочке до готового проекта.
    """
    service = _FakeFinalizedService(
        _model_claim(
            price="1 550 000 тенге",
            requests=[
                "Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты "
                "и убытки в размере 350 000 тенге.",
            ],
        )
    )

    draft = asyncio.run(service.draft_claim(_E2E_CONTEXT, _E2E_RESEARCH, language="ru"))

    assert draft.price_of_claim == ""
    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert not re.search(r"\d", draft.state_duty)
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION

    notes = "\n".join(draft.verification_notes)
    assert PRICE_UNRESOLVED_NOTE_PREFIX in notes
    assert STATE_DUTY_NOTE in draft.verification_notes

    # Ни отброшенная сумма модели, ни сумма слагаемых не попали в документ.
    body = " ".join([draft.title, draft.price_of_claim, draft.state_duty, *draft.requests])
    assert "1 550 000" not in body
    assert "15 500" not in body


def test_production_path_still_computes_the_duty_for_an_unambiguous_price() -> None:
    """Корректный сценарий не должен пострадать от fail-closed поведения."""
    service = _FakeFinalizedService(
        _model_claim(
            price="1 500 000 тенге",
            requests=["Взыскать с ответчика в пользу истца 1 200 000 тенге предварительной оплаты."],
        )
    )

    draft = asyncio.run(service.draft_claim(_E2E_CONTEXT, _E2E_RESEARCH, language="ru"))

    # Цена иска приведена к структурированному требованию, пошлина рассчитана.
    assert draft.price_of_claim == "1 200 000 тенге"
    assert draft.state_duty.startswith("12 000 тенге")
    assert PRICE_UNRESOLVED_NOTE_PREFIX not in "\n".join(draft.verification_notes)


# --------------------------------------------------------------------------
# Точные примеры из docs/agent-state/REVIEW.md (ARCH-002).
# --------------------------------------------------------------------------


def test_review_example_moral_damage_500000_is_excluded() -> None:
    """REVIEW: моральный вред 500 000 ₸ → цена 1 820 000 ₸ → пошлина 18 200 ₸."""
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга.",
        "Взыскать с ответчика в пользу истца 120 000 тенге неустойки по договору.",
        "Взыскать с ответчика в пользу истца компенсацию морального вреда в размере 500 000 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == "1 320 000 тенге"
    assert _duty(draft).startswith("13 200 тенге")


def test_review_example_penalty_formula_is_not_summed_with_its_base() -> None:
    """REVIEW: «0,1% × 1 200 000 тенге × 78 дней = 93 600 тенге» → цена 1 293 600 ₸."""
    draft = _draft([
        "Взыскать с ответчика в пользу истца неустойку: "
        "0,1% × 1 200 000 тенге × 78 дней = 93 600 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == ""
    assert _duty(draft) == NEEDS_CALCULATION_MARKER


def test_review_example_repeated_total_1320000_is_not_doubled() -> None:
    """REVIEW: требование + «Итого взыскать 1 320 000 тенге» → цена 2 640 000 ₸ → пошлина 26 400 ₸."""
    draft = _draft([
        "Взыскать с ответчика в пользу истца 1 200 000 тенге основного долга.",
        "Взыскать с ответчика в пользу истца 120 000 тенге неустойки по договору.",
        "Итого взыскать с ответчика в пользу истца 1 320 000 тенге.",
    ])

    _apply_claim_price(draft)

    assert draft.price_of_claim == "1 320 000 тенге"
    assert _duty(draft).startswith("13 200 тенге")
