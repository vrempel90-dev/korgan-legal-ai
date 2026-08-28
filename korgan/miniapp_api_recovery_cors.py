from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan.miniapp_payment_idempotency import app

# Recovery outer CORS layer. Keep the already-working Mini App origins and
# browser-managed Telegram WebView headers unchanged while the payment layer is
# hardened underneath it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://korgan-miniapp-staging-production.up.railway.app",
        "https://korgan-miniapp-web-recovery-1600-production.up.railway.app",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
