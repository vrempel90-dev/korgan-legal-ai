from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan.miniapp_api_v5 import app

# Recovery-only outer CORS layer. It preserves the production API and payment
# implementation while allowing the two KORGAN Mini App hosts used during
# incident recovery. Wildcard request headers are intentional here because
# Telegram WebView preflight may add browser-managed headers beyond the two
# application headers used by korganApi.js.
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
