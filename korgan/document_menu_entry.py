from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.i18n import KK, RU, button, normalize_language, tr
from korgan.ui import documents_menu

router = Router(name="document-menu-entry-priority")
_DOCUMENT_MENU_BUTTONS = {button(RU, "document"), button(KK, "document")}


def is_document_menu_button(text: str | None) -> bool:
    return (text or "").strip() in _DOCUMENT_MENU_BUTTONS


@router.message(F.text.in_(_DOCUMENT_MENU_BUTTONS))
async def open_document_menu(message: Message, state: FSMContext) -> None:
    """Open the document chooser on the first tap, regardless of active request mode.

    This router is intentionally included before all document waiting routers.
    A persistent reply-keyboard button is navigation, never case facts, so an
    active claim/pretrial/response/contract request must not consume it.
    """
    data = await state.get_data()
    language = normalize_language(str(data.get("language", RU)))
    await state.update_data(mode="main")
    await message.answer(
        tr(language, "documents"),
        reply_markup=documents_menu(language),
        parse_mode="HTML",
    )
