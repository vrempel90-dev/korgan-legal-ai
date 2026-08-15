from __future__ import annotations

import logging

from korgan_legal_ai.config import Settings
from korgan_legal_ai.db.engine import build_engine
from korgan_legal_ai.orchestration.factory import build_legal_engine
from korgan_legal_ai.telegram.client import TelegramBotAPI
from korgan_legal_ai.telegram.crypto import SessionCrypto
from korgan_legal_ai.telegram.postgres_session import PostgresSessionStore
from korgan_legal_ai.telegram.runtime import TelegramRuntime


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # HTTP client libraries log full request URLs at INFO. The Telegram base URL embeds the bot
    # token, and outbound legal requests carry client case text, so these loggers are held at
    # WARNING to keep secrets and case data out of application logs.
    for noisy in ("httpx", "httpcore", "openai", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for encrypted Telegram sessions")
    if not settings.telegram_session_master_key:
        raise RuntimeError("TELEGRAM_SESSION_MASTER_KEY is required")

    engine = build_legal_engine(settings)
    session_store = PostgresSessionStore(
        build_engine(settings.database_url),
        SessionCrypto.from_base64(settings.telegram_session_master_key),
        ttl_seconds=settings.telegram_session_ttl_seconds,
        max_sessions=settings.telegram_max_sessions,
    )
    # Fail fast on an unreachable database instead of discovering it on the first user message.
    session_store.ping()
    session_store.purge_expired()

    api = TelegramBotAPI(
        settings.telegram_bot_token,
        request_timeout_seconds=settings.telegram_request_timeout_seconds,
    )
    runtime = TelegramRuntime(
        api=api,
        engine=engine,
        sessions=session_store,
        privacy_version=settings.telegram_privacy_version,
        poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
        max_case_chars=settings.telegram_max_case_chars,
    )
    try:
        runtime.run_forever()
    finally:
        api.close()


if __name__ == "__main__":
    main()
