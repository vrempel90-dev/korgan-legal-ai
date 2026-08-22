from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from aiogram.fsm.context import FSMContext

from korgan.i18n import BUTTONS, KK, RU

DOCUMENT_REQUEST_KINDS = frozenset({
    "claim",
    "pretrial",
    "pretrial_response",
    "response",
    "contract",
})

_REQUEST_LOCKS: dict[tuple[object, ...], asyncio.Lock] = {}

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
    # Payment is bound to one immutable request_id. A new document request must
    # never inherit either an old receipt session or an already-confirmed payment.
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
    """Build a stable per-Telegram-session lock key across FSMContext instances."""
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
    """Return the lock shared by request replacement and final client notices."""
    key = _request_lock_key(state)
    lock = _REQUEST_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _REQUEST_LOCKS[key] = lock
    return lock


def is_main_menu_text(text: str | None) -> bool:
    """Return True for persistent navigation buttons in either client language."""
    return (text or "").strip() in _MAIN_MENU_TEXTS


def active_document_kind(data: dict) -> str | None:
    """Return the document section that owns the current request, if any."""
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
    """Return the active request id only when it still belongs to ``kind``."""
    data = await state.get_data()
    if data.get("request_kind") != kind:
        return ""
    return str(data.get("request_id") or "")


async def request_is_current(state: FSMContext, request_id: str, kind: str) -> bool:
    """Return whether an async result still belongs to the active request."""
    if not request_id:
        return False
    data = await state.get_data()
    return (
        str(data.get("request_id") or "") == request_id
        and data.get("request_kind") == kind
    )


async def start_new_document_request(
    state: FSMContext,
    *,
    kind: str,
    mode: str,
) -> str:
    """Atomically replace the active document request without touching consent settings."""
    if kind not in DOCUMENT_REQUEST_KINDS:
        raise ValueError(f"Unsupported document request kind: {kind}")

    async with document_request_lock(state):
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
        return request_id
