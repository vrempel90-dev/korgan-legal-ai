from __future__ import annotations

import logging

from korgan_legal_ai.config import Settings
from korgan_legal_ai.orchestration.factory import build_legal_engine
from korgan_legal_ai.telegram.client import TelegramBotAPI
from korgan_legal_ai.telegram.runtime import TelegramRuntime
from korgan_legal_ai.telegram.session import InMemorySessionStore


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    engine = build_legal_engine(settings)
    api = TelegramBotAPI(
        settings.telegram_bot_token,
        request_timeout_seconds=settings.telegram_request_timeout_seconds,
    )
    runtime = TelegramRuntime(
        api=api,
        engine=engine,
        sessions=InMemorySessionStore(
            ttl_seconds=settings.telegram_session_ttl_seconds,
            max_sessions=settings.telegram_max_sessions,
        ),
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
