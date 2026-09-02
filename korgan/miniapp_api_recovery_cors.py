from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan.legal.rag_runtime import install_rag_lifespan
from korgan.miniapp_payment_idempotency import app

# Mini App imports the legal runtime, but does not execute strict_bot.main().
# Attach legal corpus bootstrap directly to ASGI so both the current official
# snapshot and the broad KZ candidate corpus are available in this service.
install_rag_lifespan(app)

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
