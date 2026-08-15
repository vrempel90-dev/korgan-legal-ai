from __future__ import annotations

from typing import Any

import httpx


class TelegramAPIError(RuntimeError):
    pass


def split_text(value: str, *, limit: int = 3900) -> list[str]:
    """Split Telegram text below the Bot API 4096-char hard limit."""
    if len(value) <= limit:
        return [value]
    chunks: list[str] = []
    rest = value
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunk = rest[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        rest = rest[cut:].lstrip()
    return chunks


class TelegramBotAPI:
    def __init__(
        self,
        token: str,
        *,
        request_timeout_seconds: float = 45.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("Telegram bot token is required")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._request_timeout_seconds = request_timeout_seconds
        self._client = client or httpx.Client()

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = timeout_seconds or self._request_timeout_seconds
        try:
            response = self._client.post(
                f"{self._base_url}/{method}",
                json=payload or {},
                timeout=timeout,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            # Do not chain the original HTTP exception because its URL contains the bot token.
            raise TelegramAPIError(f"Telegram API request failed: {method}") from None
        if not body.get("ok"):
            description = str(body.get("description") or "unknown error")
            raise TelegramAPIError(f"Telegram API rejected {method}: {description}")
        return body.get("result")

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe")

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> bool:
        return bool(
            self._call(
                "deleteWebhook",
                {"drop_pending_updates": drop_pending_updates},
            )
        )

    def set_my_commands(self, commands: list[dict[str, str]]) -> bool:
        return bool(self._call("setMyCommands", {"commands": commands}))

    def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call(
            "getUpdates",
            payload,
            timeout_seconds=max(self._request_timeout_seconds, timeout_seconds + 10),
        )
        return list(result or [])

    def send_message(
        self,
        chat_id: int,
        value: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        chunks = split_text(value)
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if index == len(chunks) - 1 and reply_markup is not None:
                payload["reply_markup"] = reply_markup
            self._call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def close(self) -> None:
        self._client.close()
