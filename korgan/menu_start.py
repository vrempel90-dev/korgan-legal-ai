from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.ui import MAIN_TEXT, WELCOME_TEXT, main_menu

router = Router(name="korgan-menu-start")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.set_data({"language": "ru", "documents": [], "facts": []})
    await message.answer(WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu())


@router.message(Command("menu"))
async def menu(message: Message) -> None:
    await message.answer(MAIN_TEXT, parse_mode="HTML", reply_markup=main_menu())
