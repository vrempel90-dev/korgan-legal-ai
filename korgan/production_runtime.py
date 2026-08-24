"""Production entry point for KORGAN Legal AI.

The Telegram handlers live in :mod:`korgan.bot`, but production must use the
fully guarded legal service (verified research, civil-claim QA, deterministic
calculations and final state-duty normalization), not the base MVP service.

Keeping the wiring here avoids duplicating the bot and makes the production
service choice explicit and regression-testable.
"""

from __future__ import annotations

import asyncio

from korgan import bot as bot_module
from korgan.state_duty_final_hotfix import ProductionOpenAILegalService


async def main() -> None:
    # bot.main() instantiates the symbol named OpenAILegalService in korgan.bot.
    # Patch it only at process startup, not at module import, so importing this
    # entrypoint in tests cannot mutate unrelated runtime modules.
    bot_module.OpenAILegalService = ProductionOpenAILegalService
    await bot_module.main()


if __name__ == "__main__":
    asyncio.run(main())
