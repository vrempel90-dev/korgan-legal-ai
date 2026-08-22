from __future__ import annotations

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name="korgan-auto-payment-runtime")


class AutoPaymentReceiptFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "payment_receipt" and bool(message.photo or message.document)


def install_auto_payment() -> None:
    """Keep legacy payment copy aligned with the fail-closed manual-confirmation flow."""
    from korgan import payment_gate

    def auto_payment_offer_text(kind: str, language: str, amount: int) -> str:
        from korgan.payment import document_label

        label = document_label(kind, language)
        formatted = f"{amount:,}".replace(",", " ")
        if language == "kk":
            return (
                "💳 Құжат дайын\n\n"
                f"Қызмет құны: {formatted} ₸\n"
                f"Құжат: {label}.\n\n"
                "Word-файл чек KORGAN AI-тексеруден және әкімшінің төлемді растауынан кейін беріледі.\n"
                "1. Kaspi арқылы төлеңіз.\n"
                "2. «✅ Төледім» түймесін басыңыз.\n"
                "3. Толық чекті фото немесе PDF түрінде жіберіңіз.\n\n"
                "AI чек сомасын, сәтті төлем мәртебесін және көрінетін реквизиттерді тексереді. "
                "Содан кейін әкімші төлемді Kaspi тарихымен салыстырады."
            )
        return (
            "💳 Документ готов\n\n"
            f"Стоимость: {formatted} ₸\n"
            f"Документ: {label}.\n\n"
            "Word-файл будет выдан после проверки чека KORGAN AI и подтверждения платежа администратором.\n"
            "1. Оплатите через Kaspi.\n"
            "2. Нажмите «✅ Я оплатил».\n"
            "3. Пришлите полный чек фото или PDF.\n\n"
            "AI проверит сумму, успешный статус платежа и видимые реквизиты. "
            "Затем администратор сверит платёж с историей Kaspi."
        )

    payment_gate.payment_offer_text = auto_payment_offer_text


@router.message(AutoPaymentReceiptFilter())
async def auto_payment_receipt_received(message: Message, state: FSMContext) -> None:
    """Never auto-release: reuse the canonical AI-precheck + admin-confirmation handler."""
    from korgan.payment_runtime import payment_receipt_received

    await payment_receipt_received(message, state)
