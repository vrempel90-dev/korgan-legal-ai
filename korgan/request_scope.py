from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
_REQUEST_LOCKS = tuple(asyncio.Lock() for _ in range(64))

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
    # Payment is bound to one immutable request_id. A new document request must
    # never inherit either an old receipt session or an already-confirmed payment.
    "payment_admin_doc_message_id",
    "payment_kind",
    "payment_language",
    "payment_signature",
    "payment_confirmed_transaction_id",
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

# These are persistent reply-keyboard actions, not legal facts. A document flow
# waiting for text must always yield to them on the first tap.
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


def is_main_menu_text(text: str | None) -> bool:
    """Return True for persistent navigation buttons in either client language."""
    return (text or "").strip() in _MAIN_MENU_TEXTS


def active_document_kind(data: dict) -> str | None:
    """Return the document section that owns the current request, if any.

    A selected document button is the source of truth for the request. Words such
    as «договор», «претензия» or «отзыв» inside case facts must never move the
    client into another document workflow. Switching sections requires starting
    another request through its document button/callback.
    """
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
    """Protect clients from results produced by a request they already left.

    Legal drafting can take several seconds. During that time the client may open
    another document. The old task must then become silent: it may finish its
    internal work, but it must never release a DOCX or trigger the payment gate.
    """
    if not request_id:
        return False
    data = await state.get_data()
    return (
        str(data.get("request_id") or "") == request_id
        and data.get("request_kind") == kind
    )


def _request_lock(state: FSMContext) -> asyncio.Lock:
    key = getattr(state, "key", None)
    lock_key = key if key is not None else id(state)
    return _REQUEST_LOCKS[hash(lock_key) % len(_REQUEST_LOCKS)]


async def update_current_request(
    state: FSMContext,
    request_id: str,
    kind: str,
    *,
    clear_keys: tuple[str, ...] = (),
    **updates: object,
) -> bool:
    """Compare and update one request scope without racing a replacement request."""
    if not request_id:
        return False
    async with _request_lock(state):
        data = dict(await state.get_data())
        if (
            str(data.get("request_id") or "") != request_id
            or data.get("request_kind") != kind
        ):
            return False
        for key in clear_keys:
            data.pop(key, None)
        data.update(updates)
        await state.set_data(data)
        return True


async def run_for_current_request(
    state: FSMContext,
    request_id: str,
    kind: str,
    operation: Callable[[], Awaitable[None]],
) -> bool:
    """Run one delivery while preventing the request from being replaced."""
    if not request_id:
        return False
    async with _request_lock(state):
        data = await state.get_data()
        if (
            str(data.get("request_id") or "") != request_id
            or data.get("request_kind") != kind
        ):
            return False
        await operation()
        return True


async def start_new_document_request(
    state: FSMContext,
    *,
    kind: str,
    mode: str,
) -> str:
    """Start a clean legal-document request without touching consent/session settings.

    Every explicit document selection gets a fresh request id and empty case
    materials. This prevents facts/uploads from a previous matter from triggering
    generation of a new document before the user supplies new materials.
    """
    if kind not in DOCUMENT_REQUEST_KINDS:
        raise ValueError(f"Unsupported document request kind: {kind}")

    async with _request_lock(state):
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
