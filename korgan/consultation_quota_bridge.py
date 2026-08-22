from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram.methods import SendMessage

from korgan.config import Settings, get_settings
from korgan.kazakh_ui import KazakhLegalText

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL: Callable[..., Awaitable[bool]] | None = None
_BOT_CALL_ORIGINAL: Callable[..., Awaitable[Any]] | None = None


def _format_amount(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def polish_consultation_quota_notice(text: str, settings: Settings) -> str:
    """Turn terse quota counters into clear client-facing warnings.

    The consultation runtime remains the source of truth for counting.  This
    bridge changes presentation only, so payment/document/legal routing cannot
    be affected by the warning copy.
    """
    limit = settings.free_consultations_per_day
    price = _format_amount(settings.consultation_price_kzt)

    if text == "🆓 Бесплатных консультаций сегодня осталось: 1.":
        return (
            "⚠️ Осталась 1 бесплатная консультация на сегодня.\n\n"
            f"Вы использовали {max(limit - 1, 0)} из {limit} бесплатных консультаций. "
            f"После следующей бесплатной консультации каждый новый запрос будет стоить {price} ₸."
        )
    if text == "🆓 Бесплатных консультаций сегодня осталось: 0.":
        return (
            "ℹ️ Бесплатный лимит консультаций на сегодня исчерпан.\n\n"
            f"Вы использовали {limit} из {limit} бесплатных консультаций. "
            f"Следующий запрос будет стоить {price} ₸. Оплата через Kaspi потребуется только при следующем обращении."
        )
    if text == "🆓 Бүгін тегін кеңес қалды: 1.":
        return (
            "⚠️ Бүгін 1 тегін кеңес қалды.\n\n"
            f"Сіз {limit} тегін кеңестің {max(limit - 1, 0)}-ін пайдаландыңыз. "
            f"Келесі тегін кеңестен кейін әрбір жаңа сұрау {price} ₸ тұрады."
        )
    if text == "🆓 Бүгін тегін кеңес қалды: 0.":
        return (
            "ℹ️ Бүгінгі тегін кеңес лимиті толық пайдаланылды.\n\n"
            f"Сіз {limit} тегін кеңестің {limit}-ін пайдаландыңыз. "
            f"Келесі сұрау {price} ₸ тұрады. Kaspi арқылы төлем келесі өтініш кезінде ғана қажет болады."
        )
    return text


def install_consultation_quota_bridge() -> None:
    """Keep RU/KK quota behavior aligned and polish quota-limit notices.

    The Kazakh router is intentionally registered before the generic base router.
    Without this bridge it would answer consultations before the persistent quota
    handler sees them.  We patch only the filter decision while the consultation
    limit feature flag is enabled.  The transport wrapper changes only the two
    quota-counter messages emitted after the fourth/fifth free consultation.
    Document/menu/legal generation routing is untouched.
    """
    global _INSTALLED, _ORIGINAL, _BOT_CALL_ORIGINAL
    if _INSTALLED:
        return

    original = KazakhLegalText.__call__
    _ORIGINAL = original

    async def quota_aware(self: KazakhLegalText, message: Any, state: Any) -> bool:
        if get_settings().consultation_limit_enabled:
            return False
        return await original(self, message, state)

    KazakhLegalText.__call__ = quota_aware  # type: ignore[method-assign]

    # Message.answer() executes a SendMessage through Bot.__call__.  Wrapping the
    # existing localized bot call lets us improve only the quota notice text and
    # still delegate document/payment/localization behavior to the original code.
    from korgan.localized_transport import LocalizedClientSafeBot

    original_bot_call = LocalizedClientSafeBot.__call__
    _BOT_CALL_ORIGINAL = original_bot_call

    async def quota_notice_call(
        self: LocalizedClientSafeBot,
        method: Any,
        request_timeout: int | None = None,
    ) -> Any:
        if isinstance(method, SendMessage) and get_settings().consultation_limit_enabled:
            polished = polish_consultation_quota_notice(str(method.text or ""), get_settings())
            if polished != method.text:
                method = method.model_copy(update={"text": polished})
        return await original_bot_call(self, method, request_timeout=request_timeout)

    LocalizedClientSafeBot.__call__ = quota_notice_call  # type: ignore[method-assign]
    _INSTALLED = True
    LOGGER.info("KORGAN Kazakh consultation quota bridge and quota notices installed")
