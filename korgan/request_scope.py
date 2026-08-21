from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from aiogram.fsm.context import FSMContext

from korgan.i18n import BUTTONS, KK, RU

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
