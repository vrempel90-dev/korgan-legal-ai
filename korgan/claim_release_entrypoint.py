from __future__ import annotations

import asyncio
import logging

from korgan import bot
from korgan import claim_quality_hotfix
from korgan.claim_corpus_health import legal_grounding_readiness
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.legal_calc import rates_freshness

LOGGER = logging.getLogger(__name__)

#: За сколько дней до обрыва справочника предупреждать в логе.
_RATES_WARNING_DAYS = 14


def _log_rates_freshness() -> None:
    """Сказать в лог, сколько дней справочнику ставок осталось.

    Обрыв справочника отрабатывает правильно: неустойка не считается, а
    помечается как требующая проверки. Но узнать о нём до сих пор можно было
    либо из `/health`, куда никто не смотрит без повода, либо из уже выданного
    клиенту документа. Строка при старте кладёт тот же факт туда, где дежурный
    его увидит, — и до того, как обрыв дойдёт до людей.
    """
    state = rates_freshness()
    for what, days, stale in (
        ("базовая ставка НБ РК", state["nb_base_rate_days_left"], state["nb_base_rate_stale"]),
        ("МРП", state["mrp_days_left"], state["mrp_stale"]),
    ):
        if stale:
            LOGGER.error("RATES_STALE %s: справочник кончился %d дн. назад", what, -days)
        elif days <= _RATES_WARNING_DAYS:
            LOGGER.warning("RATES_EXPIRING %s: осталось %d дн.", what, days)
        else:
            LOGGER.info("RATES_OK %s: осталось %d дн.", what, days)


def _log_legal_grounding() -> None:
    """Сказать в лог, выпустится ли вообще правовое обоснование.

    Без собранного локального корпуса Adilet финальная сверка не пропускает ни
    одной статьи, и каждый иск выходит без раздела о праве. Это не сбой
    выполнения — конвейер отрабатывает и отдаёт предварительный документ, — но
    для юридического продукта это отказ, и дежурный должен узнать о нём при
    старте, а не по документу, уже ушедшему клиенту.
    """
    state = legal_grounding_readiness()
    if state["ready"]:
        LOGGER.info("LEGAL_GROUNDING_OK локальный корпус Adilet: %d положений", state["provisions"])
    else:
        LOGGER.error("LEGAL_GROUNDING_DISABLED %s", state["reason"])


def main() -> None:
    """Install guarded claim runtime and use the finalized professional service."""
    _log_rates_freshness()
    _log_legal_grounding()
    claim_quality_hotfix.install_runtime_hotfix()

    # Keep bot.py and every existing handler untouched. Railway starts through
    # this entrypoint, so replacing the service factory here upgrades the live
    # claim path while preserving the same Bot/FSM/router lifecycle and all
    # inherited consultation/document-intake methods.
    bot.OpenAILegalService = FinalizedProductionClaimService
    asyncio.run(bot.main())


if __name__ == "__main__":
    main()
