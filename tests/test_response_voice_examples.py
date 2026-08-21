from __future__ import annotations

from korgan.response_voice_guard import own_voice_issues


def test_reported_pretrial_response_phrases_are_blocked() -> None:
    samples = [
        "Со стороны ТОО «Восток Строй 888» на настоящий момент нет подтвержденного согласия с размером суммы.",
        "ТОО «Восток Строй 888» выражает готовность рассмотреть предоставленные документы.",
        "Правовая оценка на момент подготовки ответа не проведена.",
    ]
    assert own_voice_issues(samples)


def test_response_to_claim_self_narration_is_blocked_too() -> None:
    assert own_voice_issues([
        "Ответчик считает требования истца необоснованными.",
        "Ответчик просит отказать в удовлетворении иска.",
    ])
