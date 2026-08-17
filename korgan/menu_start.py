from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.i18n import KK, RU, normalize_language, tr
from korgan.legal_safety import has_current_consent, privacy_text, show_terms, terms_text, terms_keyboard
from korgan.ui import language_menu, main_menu

router = Router(name="korgan-menu-start")


async def _show_language_choice(message: Message) -> None:
    await message.answer(tr(RU, "choose_language"), reply_markup=language_menu())


async def _set_language_and_continue(
    *,
    language: str,
    state: FSMContext,
    message: Message,
) -> None:
    lang = normalize_language(language)
    await state.update_data(language=lang, language_selected=True)
    if not await has_current_consent(state):
        await show_terms(message, lang)
        return
    await message.answer(tr(lang, "language_set"), reply_markup=main_menu(lang))
    await message.answer(tr(lang, "main"), parse_mode="HTML", reply_markup=main_menu(lang))


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data:
        await state.set_data({"language": RU, "language_selected": False, "documents": [], "facts": []})
        await _show_language_choice(message)
        return

    if not data.get("language_selected"):
        await _show_language_choice(message)
        return

    lang = normalize_language(data.get("language", RU))
    if not await has_current_consent(state):
        await show_terms(message, lang)
        return
    await message.answer(tr(lang, "welcome"), parse_mode="HTML", reply_markup=main_menu(lang))


@router.callback_query(F.data == "lang:kk")
async def language_kk_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _set_language_and_continue(language=KK, state=state, message=callback.message)


@router.callback_query(F.data == "lang:ru")
async def language_ru_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await _set_language_and_continue(language=RU, state=state, message=callback.message)


@router.message(Command("kk"))
async def language_kk_command(message: Message, state: FSMContext) -> None:
    await _set_language_and_continue(language=KK, state=state, message=message)


@router.message(Command("ru"))
async def language_ru_command(message: Message, state: FSMContext) -> None:
    await _set_language_and_continue(language=RU, state=state, message=message)


@router.message(Command("language"))
async def language_command(message: Message) -> None:
    await _show_language_choice(message)


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_language(data.get("language", RU))
    if not await has_current_consent(state):
        await show_terms(message, lang)
        return
    await message.answer(tr(lang, "main"), parse_mode="HTML", reply_markup=main_menu(lang))


@router.message(Command("terms"))
async def terms(message: Message, state: FSMContext) -> None:
    lang = normalize_language((await state.get_data()).get("language", RU))
    await message.answer(terms_text(lang), parse_mode="HTML", reply_markup=terms_keyboard(lang))


@router.message(Command("privacy"))
async def privacy(message: Message, state: FSMContext) -> None:
    lang = normalize_language((await state.get_data()).get("language", RU))
    await message.answer(privacy_text(lang), parse_mode="HTML")
