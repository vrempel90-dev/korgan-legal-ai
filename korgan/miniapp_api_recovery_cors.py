from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi.middleware.cors import CORSMiddleware

# Professional Mini App production must fail closed on legal citations. The
# verifier may still be explicitly disabled for an emergency rollback, but an
# omitted Railway variable must never silently turn current-law verification off.
os.environ.setdefault("KORGAN_LIVE_ARTICLE_VERIFY", "on")

from korgan.miniapp_payment_idempotency import app
from korgan import fast_professional_repair_guard as _fast_professional_repair_guard  # noqa: F401
from korgan import miniapp_generation_api as _miniapp_generation_api  # noqa: F401
from korgan import document_truth_runtime as _document_truth_runtime  # noqa: F401
from korgan import live_article_release_runtime as _live_article_release_runtime  # noqa: F401
from korgan import senior_document_drafting_runtime as _senior_document_drafting_runtime  # noqa: F401
from korgan import miniapp_professional_consultation_runtime as _miniapp_professional_consultation_runtime  # noqa: F401
from korgan import miniapp_case_activity as _miniapp_case_activity  # noqa: F401
from korgan import miniapp_case_activity_cleanup as _miniapp_case_activity_cleanup  # noqa: F401

# Keep the already-tested payment/runtime stack as the owner of the ASGI app.
# Manual payment review stays available as the legacy fallback. When the three
# server-side Tole secrets are configured, the Tole runtime imported immediately
# afterwards replaces only the document-payment routes with signed automatic QR
# confirmation; consultation payments and document idempotency stay untouched.
from korgan import miniapp_manual_payment_admin as _miniapp_manual_payment_admin  # noqa: F401
from korgan import miniapp_consultation_quota_api as _miniapp_consultation_quota_api  # noqa: F401
from korgan import miniapp_tole_payments as _miniapp_tole_payments  # noqa: F401
# Install only after Tole owns its routes: the wrapper turns a verified `paid`
# transition into the durable generation job without requiring another client tap.
from korgan import miniapp_paid_autostart_runtime as _miniapp_paid_autostart_runtime  # noqa: F401
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
_KNOWN_ORIGINS = (
    "https://korgan-miniapp-staging-production.up.railway.app",
    "https://korgan-miniapp-web-recovery-1600-production.up.railway.app",
    "https://korgan-miniapp-live-clean-production.up.railway.app",
)


def _origin_of(url: str) -> str:
    """Origin ссылки: только https-схема и хост, без пути и параметров."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return f"https://{parts.netloc}"


def allowed_origins(public_url: str | None = None) -> list[str]:
    """Известные адреса Mini App плюс тот, который сервис объявил сам.

    `MINIAPP_PUBLIC_URL` — это адрес кнопки, которую бот регистрирует в
    Telegram, то есть origin страницы в WebView. Пока список был закрытым, он
    расходился с этим адресом молча: preflight отвечал 400, браузер обрывал
    каждый запрос до отправки, и Mini App показывал «Не удалось подключиться»
    на всех вкладках, ничего не оставляя в логах сервера.
    """
    raw = os.getenv("MINIAPP_PUBLIC_URL", "") if public_url is None else public_url
    origins = list(_KNOWN_ORIGINS)
    published = _origin_of(raw)
    if published and published not in origins:
        origins.append(published)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
