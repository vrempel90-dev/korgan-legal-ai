from __future__ import annotations

import asyncio

from korgan import bot
from korgan import claim_quality_hotfix


def main() -> None:
    """Install the patched claim runtime before starting the Railway worker."""
    claim_quality_hotfix.install_runtime_hotfix()
    asyncio.run(bot.main())


if __name__ == "__main__":
    main()
