from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from korgan.telegram_branding import _AVATAR_JPEG_B64, BRAND_REVISION, ensure_telegram_profile_branding


def test_korgan_brand_avatar_is_embedded_jpeg() -> None:
    image = base64.b64decode(_AVATAR_JPEG_B64)
    assert image.startswith(b"\xff\xd8\xff")
    assert image.endswith(b"\xff\xd9")
    assert len(image) > 5_000
    assert BRAND_REVISION.startswith("korgan-wordmark-")


def test_branding_is_fail_open_without_database() -> None:
    settings = SimpleNamespace(database_url="", telegram_bot_token="test-token")
    assert asyncio.run(ensure_telegram_profile_branding(settings)) is False
