from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.config import Settings, get_settings
from korgan.i18n import KK, RU, button
from korgan.ui import main_menu

router = Router(name="korgan-consultation-ui-runtime")


def consultation_prompt_text(language: str, settings: Settings) -> str:
    if language == KK:
        base = "⚖️ Жағдайды бір хабарламада сипаттаңыз. Құжаттар немесе скандар болса, осы чатқа жіберіңіз."
        if settings.consultation_limit_enabled:
            return (
                base
                + f"\n\n🆓 Күніне алғашқы {settings.free_consultations_per_day} кеңес тегін. "
                + f"Одан кейін әр кеңес — {settings.consultation_price_kzt:,} ₸.".replace(",", " ")
            )
        return base

    base = "⚖️ Опишите ситуацию одним сообщением. Если есть документы или сканы — отправьте их в этот чат."
    if settings.consultation_limit_enabled:
        return (
            base
            + f"\n\n🆓 Первые {settings.free_consultations_per_day} консультаций в сутки бесплатно. "
            + f"Далее каждая консультация — {settings.consultation_price_kzt:,} ₸.".replace(",", " ")
        )
    return base


def prices_text(language: str, settings: Settings) -> str:
    doc_price = f"{settings.document_price_kzt:,}".replace(",", " ")
    consult_price = f"{settings.consultation_price_kzt:,}".replace(",", " ")
    payment_note_ru = "💳 Оплата документов — через Kaspi." if settings.payments_enabled else "⏳ Оплата документов временно отключена."
    payment_note_kk = "💳 Құжаттар Kaspi арқылы төленеді." if settings.payments_enabled else "⏳ Құжаттар үшін төлем уақытша өшірілген."

    if language == KK:
        consultation = (
            f"\n\n⚖️ Кеңес беру\n• Күніне алғашқы {settings.free_consultations_per_day} сұрау — тегін\n"
            f"• Одан кейін әр сұрау — {consult_price} ₸"
            if settings.consultation_limit_enabled
            else ""
        )
        return (
            "💰 KORGAN бағалары\n\n"
            f"🔥 Кез келген заңдық құжат — {doc_price} ₸\n\n"
            f"• Талап қою арызы — {doc_price} ₸\n"
            f"• Шағым — {doc_price} ₸\n"
            f"• Шарт — {doc_price} ₸\n"
            f"• Талапқа пікір — {doc_price} ₸\n"
            f"• Сотқа дейінгі талап — {doc_price} ₸"
            + consultation
            + f"\n\n{payment_note_kk}"
        )

    consultation = (
        f"\n\n⚖️ Консультации\n• Первые {settings.free_consultations_per_day} запросов в сутки — бесплатно\n"
        f"• Далее каждый запрос — {consult_price} ₸"
        if settings.consultation_limit_enabled
        else ""
    )
    return (
        "💰 Цены KORGAN\n\n"
        f"🔥 Любой юридический документ — {doc_price} ₸\n\n"
        f"• Исковое заявление — {doc_price} ₸\n"
        f"• Жалоба — {doc_price} ₸\n"
        f"• Договор — {doc_price} ₸\n"
        f"• Отзыв на иск — {doc_price} ₸\n"
        f"• Досудебная претензия — {doc_price} ₸"
        + consultation
        + f"\n\n{payment_note_ru}"
    )


@router.message(F.text == button(RU, "consultation"))
async def consultation_button_ru(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    await state.update_data(mode="consultation")
    await message.answer(consultation_prompt_text(RU, settings), reply_markup=main_menu(RU))


@router.message(F.text == button(KK, "consultation"))
async def consultation_button_kk(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    await state.update_data(mode="consultation")
    await message.answer(consultation_prompt_text(KK, settings), reply_markup=main_menu(KK))


@router.message(F.text == button(RU, "prices"))
async def prices_button_ru(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(prices_text(RU, get_settings()), reply_markup=main_menu(RU))


@router.message(F.text == button(KK, "prices"))
async def prices_button_kk(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(prices_text(KK, get_settings()), reply_markup=main_menu(KK))
