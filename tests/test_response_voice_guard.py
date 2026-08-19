from __future__ import annotations

from pathlib import Path

from korgan.response_voice_guard import own_voice_issues


def test_rejects_third_person_self_narration_from_pretrial_response() -> None:
    issues = own_voice_issues([
        "Со стороны ТОО «Восток Строй 888» отсутствует подтвержденная позиция о полном признании требований.",
        "ТОО «Восток Строй 888» не может подтвердить размер заявленной задолженности.",
    ])
    assert "позиция автора изложена от третьего лица вместо прямой позиции стороны" in issues
    assert "в тело документа попало внутреннее рассуждение о неопределённости позиции" in issues


def test_rejects_meta_reasoning_in_own_position() -> None:
    issues = own_voice_issues([
        "Соразмерность неустойки требует отдельной правовой оценки, которая на момент подготовки ответа не проведена.",
        "Отсутствует согласованное понимание периода просрочки.",
    ])
    assert "в тело документа попало внутреннее рассуждение о неопределённости позиции" in issues


def test_allows_direct_party_voice() -> None:
    assert own_voice_issues([
        "Не признаём требование об оплате 950 000 тенге в заявленном размере.",
        "Считаем расчёт неустойки необоснованным по представленным материалам.",
        "Просим предоставить подписанный экземпляр акта сверки и детализированный расчёт.",
    ]) == []


def test_allows_third_person_description_of_opponent() -> None:
    assert own_voice_issues([
        "Истец указывает, что услуги оказаны полностью.",
        "Поставщик требует оплатить задолженность и неустойку.",
        "С доводами истца не согласны по следующим основаниям.",
    ]) == []


def test_runtime_wires_guard_without_touching_other_document_installers() -> None:
    source = Path("korgan/strict_bot.py").read_text(encoding="utf-8")
    assert "install_response_voice_guard" in source
    guard = Path("korgan/response_voice_guard.py").read_text(encoding="utf-8")
    assert "draft_pretrial_response" in guard
    assert "draft_response_to_claim" in guard
    assert "draft_claim" not in guard
    assert "draft_contract" not in guard
    assert "draft_pretrial(" not in guard
