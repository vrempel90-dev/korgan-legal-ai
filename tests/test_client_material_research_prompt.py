from __future__ import annotations

from korgan import fast_professional_litigation as litigation


def test_client_material_law_rules_are_installed_on_actual_research_prompt() -> None:
    prompt = litigation._professional_research_prompt(
        "Спор возник из договора подряда: заявлены основной долг и неустойка.",
        max_chars=12000,
        checked_on="2026-08-22",
    )

    assert "МАТЕРИАЛЬНО-ПРАВОВОЕ ПОКРЫТИЕ ДОКУМЕНТА" in prompt
    assert "Процессуальная норма не заменяет материальную" in prompt
    assert "Для КАЖДОГО самостоятельного" in prompt
    assert "специальный закон" in prompt
    assert "source-bound VERIFIED-подтверждения" in prompt
    assert "Разделяй материальные и процессуальные основания" in prompt
