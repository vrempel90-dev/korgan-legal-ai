from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import uvicorn


def _telegram_api(token: str, method: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram Bot API {method} failed")
    return data


def register_miniapp_menu() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    miniapp_url = os.getenv("MINIAPP_PUBLIC_URL", "").strip()
    button_text = os.getenv("TELEGRAM_MINIAPP_MENU_TEXT", "Открыть KORGAN").strip() or "Открыть KORGAN"

    if not token:
        print("TELEGRAM_MINIAPP_MENU_SKIPPED reason=missing_token", flush=True)
        return
    if not miniapp_url.startswith("https://"):
        print("TELEGRAM_MINIAPP_MENU_SKIPPED reason=invalid_https_url", flush=True)
        return

    try:
        me = _telegram_api(token, "getMe")
        bot = me.get("result") if isinstance(me.get("result"), dict) else {}
        username = str(bot.get("username") or "unknown")

        _telegram_api(
            token,
            "setChatMenuButton",
            {
                "menu_button": {
                    "type": "web_app",
                    "text": button_text,
                    "web_app": {"url": miniapp_url},
                }
            },
        )

        check = _telegram_api(token, "getChatMenuButton")
        result = check.get("result") if isinstance(check.get("result"), dict) else {}
        web_app = result.get("web_app") if isinstance(result.get("web_app"), dict) else {}
        registered_url = str(web_app.get("url") or "")
        registered_text = str(result.get("text") or "")
        registered_type = str(result.get("type") or "")

        if registered_type != "web_app" or registered_url != miniapp_url:
            raise RuntimeError("Telegram menu verification mismatch")

        print(
            f"TELEGRAM_MINIAPP_MENU_REGISTERED bot=@{username} text={registered_text!r} url={registered_url}",
            flush=True,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, ValueError) as exc:
        # The Mini App API must stay available even if Telegram is temporarily unreachable.
        print(f"TELEGRAM_MINIAPP_MENU_WARNING error={type(exc).__name__}", flush=True)


def main() -> None:
    register_miniapp_menu()
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("korgan.miniapp_api_v4:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
