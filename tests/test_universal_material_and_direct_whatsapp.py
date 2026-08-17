from __future__ import annotations

import inspect

from korgan.localized_transport import lawyer_consultation_markup, lawyer_consultation_text
from korgan import strict_bot


def test_runtime_uses_universal_material_law_guard() -> None:
    source = inspect.getsource(strict_bot.main)
    assert "AdditiveLegalGuardService(settings)" in source
    assert "PretrialOnlyMaterialGuardService(settings)" not in source


def test_yes_opens_whatsapp_directly_in_one_tap() -> None:
    markup = lawyer_consultation_markup("ru", "KRG-26-ABC123", "claim")
    yes = markup.inline_keyboard[0][0]
    no = markup.inline_keyboard[1][0]

    assert yes.text == "✅ Да"
    assert yes.url is not None
    assert yes.url.startswith("https://wa.me/77005000553")
    assert "KRG-26-ABC123" in yes.url
    assert yes.callback_data is None
    assert no.text == "❌ Нет"
    assert no.callback_data == "lawyer:decline"


def test_lawyer_cta_is_short_and_marks_consultation_paid() -> None:
    text = lawyer_consultation_text("ru", "KRG-26-ABC123", "claim")
    assert "Консультация персонального юриста платная" in text
    assert "+7 700 500 05 53" in text
    assert "Хотите получить консультацию" in text
    assert len(text) < 500
