from __future__ import annotations

import asyncio
import io

import pytest
from docx import Document

from korgan import document_release_resilience_runtime as runtime


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_right_modal_synonym_is_not_a_false_failure() -> None:
    provision = (
        "Заказчик вправе отказаться от договора при нарушении исполнителем существенного условия "
        "и потребовать возмещения убытков."
    )
    statement = (
        "При нарушении исполнителем существенного условия заказчик может отказаться от договора."
    )
    assert runtime.semantic_paraphrase_defects(statement, provision) == []


def test_right_restated_as_right_phrase_is_not_a_false_failure() -> None:
    provision = (
        "Заказчик вправе отказаться от договора при нарушении исполнителем существенного условия."
    )
    statement = (
        "При нарушении исполнителем существенного условия заказчик имеет право отказаться от договора."
    )
    assert runtime.semantic_paraphrase_defects(statement, provision) == []


def test_right_restated_as_duty_remains_blocked() -> None:
    provision = (
        "Заказчик вправе проверять ход и качество работ, не вмешиваясь в деятельность подрядчика."
    )
    statement = "Заказчик обязан проверять ход и качество работ подрядчика."
    defects = runtime.semantic_paraphrase_defects(statement, provision)
    assert defects
    assert any("право, а не обязанность" in item for item in defects)


def test_right_restated_as_prohibition_remains_blocked() -> None:
    provision = (
        "Заказчик вправе отказаться от договора при существенном нарушении исполнителем обязательства."
    )
    statement = "Заказчик не вправе отказаться от договора при существенном нарушении обязательства."
    assert runtime.semantic_paraphrase_defects(statement, provision)


def test_alternative_synonym_is_preserved() -> None:
    provision = (
        "Сторона вправе потребовать устранения недостатков либо соразмерного уменьшения цены договора."
    )
    statement = (
        "Сторона может потребовать устранения недостатков или соразмерного уменьшения цены договора."
    )
    assert runtime.semantic_paraphrase_defects(statement, provision) == []


def test_exclusive_synonym_is_preserved() -> None:
    provision = (
        "Возмещение производится только при наличии документально подтвержденных расходов стороны."
    )
    statement = (
        "Возмещение производится лишь при наличии документально подтвержденных расходов стороны."
    )
    assert runtime.semantic_paraphrase_defects(statement, provision) == []


def test_explicit_unresolved_placeholder_is_not_treated_as_fabricated_address() -> None:
    findings = [
        "адрес отсутствует во входящих материалах: г. Астана, "
        "[ТРЕБУЕТ УТОЧНЕНИЯ: точный адрес офиса — улица, дом]"
    ]
    assert runtime._filter_placeholder_findings(findings) == []


def test_real_fabricated_address_is_still_blocked() -> None:
    findings = ["адрес отсутствует во входящих материалах: г. Астана, ул. Достык, 12"]
    assert runtime._filter_placeholder_findings(findings) == findings


def test_runtime_is_installed_into_both_final_release_gates() -> None:
    from korgan import document_truth_runtime as truth
    from korgan import live_article_release_runtime as live
    from korgan import provision_check

    assert provision_check.paraphrase_defects is runtime.semantic_paraphrase_defects
    assert live.paraphrase_defects is runtime.semantic_paraphrase_defects
    assert truth.general_truth_findings is runtime.resilient_general_truth_findings
    assert truth.contract_truth_findings is runtime.resilient_contract_truth_findings


def test_all_five_document_types_share_the_hardened_generation_core() -> None:
    from korgan import miniapp_api_v2 as core

    assert core._DOCUMENT_TYPES == {
        "claim",
        "contract",
        "response",
        "pretrial",
        "pretrial_response",
    }


def test_article_635_style_right_synonym_passes_final_live_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the live pretrial-response failure seen at 95%."""
    from korgan import live_article_release_runtime as live

    async def scenario() -> None:
        general = live.LiveAct(
            act_id=live.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="04.09.2026",
            articles={},
        )
        special = live.LiveAct(
            act_id=live.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="04.09.2026",
            articles={
                "635": {
                    "1": (
                        "При существенном нарушении условий договора заказчик вправе отказаться "
                        "от договора и потребовать возмещения причиненных убытков."
                    )
                }
            },
        )

        async def live_act(act_id: str):
            return general if act_id == live.ACT_GK_GENERAL else special

        monkeypatch.setattr(live, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 635 ГК РК, при существенном нарушении условий договора "
            "заказчик может отказаться от договора."
        )
        await live.verify_document_articles(payload)

    asyncio.run(scenario())
