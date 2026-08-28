from __future__ import annotations

import asyncio

from korgan.prepayment_auto_payment import install_adminless_automatic_prepayment

# Install before importing strict_bot so every guarded document generator uses
# the adminless automatic prepayment function while the rest of strict_bot stays
# exactly the same production runtime.
install_adminless_automatic_prepayment()

from korgan.strict_bot import main  # noqa: E402
from korgan.claim_release_fail_closed import install_fail_closed_claim_release  # noqa: E402

# strict_bot installs all legacy/professional runtime wrappers during import.
# Install this last so no later hotfix can re-enable PRELIMINARY claim delivery.
install_fail_closed_claim_release()


if __name__ == "__main__":
    asyncio.run(main())
