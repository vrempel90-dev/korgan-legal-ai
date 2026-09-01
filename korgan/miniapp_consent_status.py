"""Серверный статус согласия для запуска Mini App.

Локальное хранилище браузера хранит только удобства интерфейса. Решение о том,
приняты ли текущие условия, приходит из зашифрованного состояния пользователя
на бэкенде.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header

router = APIRouter()


@router.get("/miniapp/consent")
async def get_consent_status(
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    # Ленивый импорт сохраняет независимость роутера от порядка сборки слоёв.
    from korgan import miniapp_api_v2 as core

    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._state(identity)
    consent = state.get("consent") or {}
    accepted = consent.get("accepted") is True
    version = str(consent.get("terms_version") or "").strip() or None
    return {"accepted": accepted, "terms_version": version}
