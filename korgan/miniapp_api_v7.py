from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from korgan import miniapp_api_v6 as runtime

app = runtime.app

# v6 inherits the original staging-only CORS policy from miniapp_api.py.
# The production OFD frontend runs on its own Railway domain, so browsers inside
# Telegram must be allowed to call the OFD API directly. Keep the legacy staging
# origin for rollback/dev parity and add the production OFD origin explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://korgan-miniapp-ofd-production.up.railway.app",
        "https://korgan-miniapp-staging-production.up.railway.app",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)
