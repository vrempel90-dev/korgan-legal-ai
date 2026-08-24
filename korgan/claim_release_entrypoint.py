from __future__ import annotations

import asyncio

from korgan import bot
from korgan import claim_quality_hotfix
from korgan.finalized_litigation import FinalizedProductionClaimService


def main() -> None:
    """Install guarded claim runtime and use the finalized professional service."""
    claim_quality_hotfix.install_runtime_hotfix()

    # Keep bot.py and every existing handler untouched. Railway starts through
    # this entrypoint, so replacing the service factory here upgrades the live
    # claim path while preserving the same Bot/FSM/router lifecycle and all
    # inherited consultation/document-intake methods.
    bot.OpenAILegalService = FinalizedProductionClaimService
    asyncio.run(bot.main())


if __name__ == "__main__":
    main()
