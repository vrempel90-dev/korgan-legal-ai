from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import uvicorn

from korgan.miniapp_professional_release import install_miniapp_professional_release_gate


def _telegram_api(token: str, method: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        description = f"HTTP {exc.code}"
        try:
            body = json.loads(exc.read().decode("utf-8"))
            description = str(body.get("description") or description)
        except Exception:
            pass
        raise RuntimeError(f"{method}: {description}") from exc

    if not data.get("ok"):
        description = str(data.get("description") or "unknown Telegram error")
        raise RuntimeError(f"{method}: {description}")
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
        print(f"TELEGRAM_MINIAPP_BOT bot=@{username}", flush=True)

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
        print(f"TELEGRAM_MINIAPP_MENU_SET bot=@{username} url={miniapp_url}", flush=True)

        last_result: dict[str, object] = {}
        for _ in range(3):
            time.sleep(0.35)
            check = _telegram_api(token, "getChatMenuButton")
            result = check.get("result") if isinstance(check.get("result"), dict) else {}
            last_result = result
            web_app = result.get("web_app") if isinstance(result.get("web_app"), dict) else {}
            registered_url = str(web_app.get("url") or "")
            registered_type = str(result.get("type") or "")
            if registered_type == "web_app" and registered_url.rstrip("/") == miniapp_url.rstrip("/"):
                registered_text = str(result.get("text") or button_text)
                print(
                    f"TELEGRAM_MINIAPP_MENU_REGISTERED bot=@{username} text={registered_text!r} url={registered_url}",
                    flush=True,
                )
                return

        actual_type = str(last_result.get("type") or "unknown")
        print(
            f"TELEGRAM_MINIAPP_MENU_VERIFY_WARNING bot=@{username} actual_type={actual_type}",
            flush=True,
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        # Telegram setup is deliberately isolated from the production AI agent
        # and must never prevent the dedicated Mini App API from starting.
        print(f"TELEGRAM_MINIAPP_MENU_WARNING detail={exc}", flush=True)


def main() -> None:
    register_miniapp_menu()
    install_miniapp_professional_release_gate()
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("korgan.miniapp_api_recovery_cors:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
