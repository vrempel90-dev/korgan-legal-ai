from __future__ import annotations

import asyncio

from korgan import bot
from korgan import claim_quality_hotfix
from korgan.config import get_settings
from korgan.token_budget_guard import apply_token_budget_guard


def main() -> None:
    """Install production guards before starting the Railway worker."""
    settings = get_settings()
    apply_token_budget_guard(settings)
    claim_quality_hotfix.install_runtime_hotfix()
    asyncio.run(bot.main())


if __name__ == "__main__":
    main()
