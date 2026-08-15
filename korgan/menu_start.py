from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.legal_safety import PRIVACY_TEXT, TERMS_TEXT, TERMS_VERSION, has_current_consent, show_terms, terms_keyboard
from korgan.ui import MAIN_TEXT, WELCOME_TEXT, main_menu

router = Router(name="korgan-menu-start")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data:
        await state.set_data({"language": "ru", "documents": [], "facts": []})
    if not await has_current_consent(state):
        await show_terms(message)
        return
    await message.answer(WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu())


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext) -> None:
    if not await has_current_consent(state):
        await show_terms(message)
        return
    await message.answer(MAIN_TEXT, parse_mode="HTML", reply_markup=main_menu())


@router.message(Command("terms"))
async def terms(message: Message) -> None:
    await message.answer(TERMS_TEXT, parse_mode="HTML", reply_markup=terms_keyboard())


@router.message(Command("privacy"))
async def privacy(message: Message) -> None:
    await message.answer(PRIVACY_TEXT, parse_mode="HTML")
