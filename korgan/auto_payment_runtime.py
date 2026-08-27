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
    """Keep legacy payment copy aligned with strict automatic AI verification."""
    from korgan import payment_gate

    def auto_payment_offer_text(kind: str, language: str, amount: int) -> str:
        from korgan.payment import document_label

        label = document_label(kind, language)
        formatted = f"{amount:,}".replace(",", " ")
        if language == "kk":
            return (
                "💳 Құжатқа төлем\n\n"
                f"Қызмет құны: {formatted} ₸\n"
                f"Құжат: {label}.\n\n"
                "Құжат чек KORGAN AI-тексеруден өткенге дейін берілмейді.\n"
                "1. Kaspi арқылы төлеңіз.\n"
                "2. «✅ Төледім» түймесін басыңыз.\n"
                "3. Толық чекті фото немесе PDF түрінде жіберіңіз.\n\n"
                "AI соманы, сәтті төлем мәртебесін, күн/уақытты, операция нөмірін және аномалияларды тексереді. "
                "Тексеру сәтті болса, құжат автоматты түрде іске қосылады/беріледі."
            )
        return (
            "💳 Оплата документа\n\n"
            f"Стоимость: {formatted} ₸\n"
            f"Документ: {label}.\n\n"
            "Документ не выдаётся до проверки чека KORGAN AI.\n"
            "1. Оплатите через Kaspi.\n"
            "2. Нажмите «✅ Я оплатил».\n"
            "3. Пришлите полный чек фото или PDF.\n\n"
            "AI проверит сумму, успешный статус, дату/время, номер операции и признаки аномалий. "
            "Если проверка пройдена, документ автоматически запускается/выдаётся без подтверждения администратора."
        )

    payment_gate.payment_offer_text = auto_payment_offer_text


@router.message(AutoPaymentReceiptFilter())
async def auto_payment_receipt_received(message: Message, state: FSMContext) -> None:
    """Delegate to the canonical strict AI-verification and auto-release handler."""
    from korgan.payment_runtime import payment_receipt_received

    await payment_receipt_received(message, state)
