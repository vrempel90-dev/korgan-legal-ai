from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from korgan.claim_intake_priority import ActiveClaimReplyFilter, ClaimButtonWhileWaitingFilter
from korgan.claim_preflight import inspect_claim_context
from korgan.field_intake import normalize_answer


CASE = """Истец: ТОО «Тест Юрист», БИН 000000000001, г. Алматы.
Ответчик: ТОО «Тест Клиент», БИН 000000000002, г. Алматы.

1 июля 2026 года между сторонами заключен договор возмездного оказания юридических и консультационных услуг №15. Стоимость услуг — 600 000 тенге.
Услуги оказаны полностью. 31 июля 2026 года сторонами подписан акт оказанных услуг №7 без замечаний и возражений.
По договору заказчик обязан оплатить услуги в течение 5 рабочих дней после подписания акта. Оплата до настоящего времени не произведена.
Досудебная претензия направлена ответчику 10 августа 2026 года и получена им в тот же день.
Основная задолженность: 600 000 тенге.
Подготовь исковое заявление о взыскании 600 000 тенге задолженности по договору оказания услуг."""

ANSWER = """Место нахождения истца: г. Алматы, ул. Абая, д. 15
Банковские реквизиты истца: IBAN KZ123456789012345678, АО «Банк»
Место нахождения ответчика: г. Алматы, Алатауский район, ул. Момышулы, 5"""


def _run(coro):
    return asyncio.run(coro)


def _state(mode: str) -> FSMContext:
    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1, user_id=1))
    _run(state.set_data({
        "mode": mode,
        "pending_fields": [
            "место нахождения истца",
            "банковские реквизиты истца",
            "место нахождения ответчика",
        ],
        "facts": [CASE],
        "language": "ru",
    }))
    return state


def test_exact_corporate_answer_clears_all_three_missing_fields() -> None:
    pending = list(inspect_claim_context(CASE).missing)
    assert pending == [
        "место нахождения истца",
        "банковские реквизиты истца",
        "место нахождения ответчика",
    ]

    intake = normalize_answer(pending, ANSWER)
    assert intake.progressed
    assert set(intake.matched) == set(pending)
    assert not intake.errors

    updated = CASE + "\n" + intake.as_case_text()
    assert inspect_claim_context(updated).missing == ()


def test_active_claim_details_text_is_reserved_for_intake() -> None:
    async def scenario() -> None:
        state = _state("claim_details")
        message = SimpleNamespace(text=ANSWER)
        assert await ActiveClaimReplyFilter()(message, state) is True

    _run(scenario())


def test_even_repeated_claim_command_is_reserved_while_waiting_for_fields() -> None:
    async def scenario() -> None:
        state = _state("claim_details")
        message = SimpleNamespace(text="Подготовь исковое заявление о взыскании 600 000 тенге")
        assert await ActiveClaimReplyFilter()(message, state) is True

    _run(scenario())


def test_navigation_button_is_not_trapped_by_claim_intake() -> None:
    async def scenario() -> None:
        state = _state("claim_details")
        message = SimpleNamespace(text="📄 Документ")
        assert await ActiveClaimReplyFilter()(message, state) is False

    _run(scenario())


def test_claim_callback_is_intercepted_without_restarting_preflight() -> None:
    async def scenario() -> None:
        state = _state("claim_details")
        callback = SimpleNamespace()
        assert await ClaimButtonWhileWaitingFilter()(callback, state) is True

    _run(scenario())
