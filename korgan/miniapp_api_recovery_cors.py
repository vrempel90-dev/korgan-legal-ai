from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan.miniapp_payment_idempotency import app

# Registers secure Mini App document delivery/access routes as side effects.
# - /document/telegram remains the reliable fallback for Telegram WebView.
# - /document/access issues short-lived signed links used by native downloadFile
#   and the protected first-party document preview.
from korgan import miniapp_telegram_delivery as _miniapp_telegram_delivery  # noqa: F401
from korgan import miniapp_document_access as _miniapp_document_access  # noqa: F401

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
