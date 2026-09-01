from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan.miniapp_payment_idempotency import app
from korgan import miniapp_generation_api as _miniapp_generation_api  # noqa: F401

# Keep the already-tested payment/runtime stack as the owner of the ASGI app.
# Manual payment review is installed after the deterministic receipt stack so it
# can replace only the document-payment upload/parity surface while preserving
# consultation payments and document idempotency.
from korgan import miniapp_manual_payment_admin as _miniapp_manual_payment_admin  # noqa: F401
from korgan import miniapp_telegram_delivery as _miniapp_telegram_delivery  # noqa: F401
from korgan import miniapp_consent_status as _miniapp_consent_status
from korgan import miniapp_document_access as _miniapp_document_access
from korgan import miniapp_qr_analytics as _miniapp_qr_analytics

app.include_router(_miniapp_consent_status.router)
app.include_router(_miniapp_document_access.router)
app.include_router(_miniapp_qr_analytics.router)

# Recovery outer CORS layer. Keep the already-working Mini App origins and
# browser-managed Telegram WebView headers unchanged while the payment layer is
# hardened underneath it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://korgan-miniapp-staging-production.up.railway.app",
        "https://korgan-miniapp-web-recovery-1600-production.up.railway.app",
        "https://korgan-miniapp-live-clean-production.up.railway.app",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
