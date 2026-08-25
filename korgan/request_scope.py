from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from aiogram.fsm.context import FSMContext

from korgan.i18n import BUTTONS, KK, RU

LOGGER = logging.getLogger(__name__)

DOCUMENT_REQUEST_KINDS = frozenset({
    "claim",
    "pretrial",
    "pretrial_response",
    "response",
    "contract",
})

_REQUEST_LOCKS: dict[tuple[object, ...], asyncio.Lock] = {}
# One heavy generation task may own a Telegram session at a time.  A newer user
# request cancels the old task before it can spend another research/draft call.
_ACTIVE_GENERATIONS: dict[tuple[object, ...], tuple[str, str, asyncio.Task]] = {}

# Only request/case-specific keys are reset. Consent, selected language,
# consultation counters and other account/session settings are preserved.
_REQUEST_SCOPED_KEYS = {
    "documents",
    "facts",
    "consulted_articles",
    "accepted_provisions",
    "claim_draft",
    "pending_fields",
    "gate_issues",
    "intake_repeats",
    "critical_answered",
    "claim_confirmation_pending",
    "claim_warning_confirmed_at",
    "claim_warning_version",
    "selected_field",
    "field_attempts",
    "pending_document_kind",
    "pending_document_request",
    "client_checklist_request_id",
    "client_checklist_kind",
    "generation_progress_request_id",
    "generation_progress_kind",
    "consultation_request_id",
    "consultation_request_started_at",
    "payment_admin_doc_message_id",
    "payment_kind",
    "payment_language",
    "payment_signature",
    "prepayment_transaction_id",
    "prepayment_request_id",
    "prepayment_kind",
    "prepayment_language",
    "prepayment_confirmed_request_id",
    "prepayment_confirmed_kind",
    "prepayment_confirmed_transaction_id",
    "prepayment_generation_started_request_id",
    "prepayment_consumed_request_id",
}

_MAIN_MENU_KEYS = (
    "consultation",
    "document",
    "prices",
    "case",
    "lawyer",
    "help",
    "support",
    "feedback",
    "language",
    "delete",
)
_MAIN_MENU_TEXTS = frozenset(
    BUTTONS[language][key]
    for language in (RU, KK)
    for key in _MAIN_MENU_KEYS
)


def _request_lock_key(state: FSMContext) -> tuple[object, ...]:
    key = getattr(state, "key", None)
    if key is None:
        return ("state", id(state))
    return (
        "telegram",
        getattr(key, "bot_id", None),
        getattr(key, "chat_id", None),
        getattr(key, "user_id", None),
        getattr(key, "thread_id", None),
    )


def document_request_lock(state: FSMContext) -> asyncio.Lock:
    key = _request_lock_key(state)
    lock = _REQUEST_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _REQUEST_LOCKS[key] = lock
    return lock


def _register_current_task(state: FSMContext, request_id: str, kind: str) -> None:
    task = asyncio.current_task()
    if task is None or not request_id:
        return
    key = _request_lock_key(state)
    existing = _ACTIVE_GENERATIONS.get(key)
    if existing is not None and existing[2] is task:
        _ACTIVE_GENERATIONS[key] = (request_id, kind, task)
        return
    _ACTIVE_GENERATIONS[key] = (request_id, kind, task)
    LOGGER.info(
        "PIPELINE_INVARIANT I10 generation_registered request_id=%s kind=%s task=%s",
        request_id,
        kind,
        id(task),
    )


def _cancel_previous_generation(state: FSMContext, *, replacement_kind: str) -> None:
    key = _request_lock_key(state)
    existing = _ACTIVE_GENERATIONS.get(key)
    if existing is None:
        return
    old_request_id, old_kind, task = existing
    current = asyncio.current_task()
    if task is current or task.done():
        if task.done():
            _ACTIVE_GENERATIONS.pop(key, None)
        return
    task.cancel()
    _ACTIVE_GENERATIONS.pop(key, None)
    LOGGER.warning(
        "PIPELINE_INVARIANT I10 stale_generation_cancelled_before_next_stage old_request_id=%s old_kind=%s replacement_kind=%s task=%s",
        old_request_id,
        old_kind,
        replacement_kind,
        id(task),
    )


def is_main_menu_text(text: str | None) -> bool:
    return (text or "").strip() in _MAIN_MENU_TEXTS


def active_document_kind(data: dict) -> str | None:
    kind = str(data.get("request_kind") or "")
    request_id = str(data.get("request_id") or "")
    if request_id and kind in DOCUMENT_REQUEST_KINDS:
        return kind
    return None


def request_label(kind: str, language: str = "ru") -> str:
    kk = language == "kk"
    labels = {
        "claim": "Талап қою арызы" if kk else "Исковое заявление",
        "pretrial": "Сотқа дейінгі талап" if kk else "Досудебная претензия",
        "pretrial_response": "Сотқа дейінгі талапқа жауап" if kk else "Ответ на претензию",
        "response": "Талап қою арызына пікір" if kk else "Отзыв на иск",
        "contract": "Шарт" if kk else "Договор",
    }
    return labels.get(kind, kind)


async def current_request_id(state: FSMContext, kind: str) -> str:
    """Return the active request id and register this handler as its heavy task."""
    data = await state.get_data()
    if data.get("request_kind") != kind:
        return ""
    request_id = str(data.get("request_id") or "")
    _register_current_task(state, request_id, kind)
    return request_id


async def request_is_current(state: FSMContext, request_id: str, kind: str) -> bool:
    if not request_id:
        return False
    data = await state.get_data()
    return (
        str(data.get("request_id") or "") == request_id
        and data.get("request_kind") == kind
    )


async def start_new_consultation_request(state: FSMContext) -> str:
    """Replace a consultation token and cancel any older heavy generation first."""
    async with document_request_lock(state):
        _cancel_previous_generation(state, replacement_kind="consultation")
        request_id = uuid4().hex
        await state.update_data(
            consultation_request_id=request_id,
            consultation_request_started_at=datetime.now(timezone.utc).isoformat(),
        )
        _register_current_task(state, request_id, "consultation")
        return request_id


async def consultation_request_is_current(state: FSMContext, request_id: str) -> bool:
    if not request_id:
        return False
    data = await state.get_data()
    return str(data.get("consultation_request_id") or "") == request_id


async def start_new_document_request(
    state: FSMContext,
    *,
    kind: str,
    mode: str,
) -> str:
    """Atomically replace the request and cancel the previous heavy task first."""
    if kind not in DOCUMENT_REQUEST_KINDS:
        raise ValueError(f"Unsupported document request kind: {kind}")

    async with document_request_lock(state):
        _cancel_previous_generation(state, replacement_kind=kind)
        data = dict(await state.get_data())
        for key in _REQUEST_SCOPED_KEYS:
            data.pop(key, None)

        request_id = uuid4().hex
        data.update(
            {
                "documents": [],
                "facts": [],
                "consulted_articles": [],
                "mode": mode,
                "request_kind": kind,
                "request_id": request_id,
                "request_started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await state.set_data(data)
        LOGGER.info(
            "PIPELINE_INVARIANT I10 request_replaced request_id=%s kind=%s result=PASS",
            request_id,
            kind,
        )
        return request_id
