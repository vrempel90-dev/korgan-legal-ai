from __future__ import annotations

from korgan.professional_consultation_guard import _render_consultation, _safe_free_text


VERIFIED = [(
    "Гражданские права могут защищаться предусмотренными законом способами.",
    "статья 9 ГК РК",
    "https://adilet.zan.kz/rus/docs/K940001000_",
)]


def test_numeric_percentage_word_is_blocked_outside_verified_block() -> None:
    assert _safe_free_text("Неустойка составляет 1 процент в день.") == ""
    assert _safe_free_text("Айыппұл мөлшері күніне 1 пайыз.") == ""


def test_calendar_deadline_is_blocked_outside_verified_block() -> None:
    assert _safe_free_text("Подайте жалобу не позднее 1 сентября 2026 года.") == ""
    assert _safe_free_text("Подайте жалобу до 1 сентября 2026 года.") == ""


def test_renderer_drops_unverified_rate_and_calendar_deadline() -> None:
    payload = {
        "recommended_actions": [
            "Соберите договор и подтверждение оплаты.",
            "Подайте жалобу не позднее 1 сентября 2026 года.",
            "Неустойка составляет 1 процент в день.",
        ],
        "verified_points": [],
        "unverified_claims": ["Ставка составляет один процент."],
    }

    answer = _render_consultation(payload, VERIFIED, [], language="ru")

    assert "Соберите договор и подтверждение оплаты" in answer
    assert "1 сентября 2026" not in answer
    assert "1 процент" not in answer
    assert "один процент" not in answer
