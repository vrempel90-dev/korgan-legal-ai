from __future__ import annotations

import io
import re

from docx import Document

from korgan.contract_docx import build_contract_docx
from korgan.contract_numbering import iter_numbered_paragraphs, split_leading_number
from korgan.contract_preamble import ensure_identified_preamble, preamble_defects
from korgan.legal_types import ContractDraft, ContractSection, VerificationStatus


# A raw model payload reproducing both defects seen in the shipped drafts:
# literal numbering written into headings and clauses, and a preamble that jumps
# straight to "совместно именуемые «Стороны»".
_DEFECTIVE_PAYLOAD = {
    "contract_type": "договор возмездного оказания услуг",
    "title": "ДОГОВОР ВОЗМЕЗДНОГО ОКАЗАНИЯ УСЛУГ № 1",
    "place_and_date": "г. Алматы, 16.08.2026",
    "party_a": ["ТОО «Астана Логистик», БИН 123456789012"],
    "party_b": ["ИП Сериков А.Б., ИИН 900101300123"],
    "preamble": ["совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем."],
    "sections": [
        {
            "heading": "1. Предмет Договора",
            "clauses": [
                {"text": "1.1. По настоящему Договору Исполнитель обязуется оказать услуги.", "subclauses": []},
                {"text": "1.2. Перечень услуг определяется Приложением № 1.", "subclauses": []},
            ],
        },
        {
            "heading": "3. Ответственность Сторон",
            "clauses": [
                {"text": "3.1. Стороны несут ответственность в соответствии с законодательством.", "subclauses": []},
                {"text": "3.1.1. Заказчик отвечает за достоверность переданных сведений.", "subclauses": []},
                {"text": "3.1.2. Исполнитель отвечает за качество услуг.", "subclauses": []},
            ],
        },
    ],
    "requisites_a": ["ТОО «Астана Логистик», БИН 123456789012"],
    "requisites_b": ["ИП Сериков А.Б., ИИН 900101300123"],
    "verification_notes": [],
}


def _draft_from(payload: dict) -> ContractDraft:
    return ContractDraft.from_payload(
        status=VerificationStatus.NEEDS_VERIFICATION,
        source_urls=[],
        payload=payload,
    )


def _docx_lines(draft: ContractDraft) -> list[str]:
    doc = Document(io.BytesIO(build_contract_docx(draft)))
    return [p.text for p in doc.paragraphs if p.text.strip()]


def test_leading_numbers_are_split_off() -> None:
    assert split_leading_number("1. Предмет Договора") == (1, "Предмет Договора")
    assert split_leading_number("1.1. По настоящему Договору") == (2, "По настоящему Договору")
    assert split_leading_number("3.1.1. Заказчик отвечает") == (3, "Заказчик отвечает")
    assert split_leading_number("Раздел 2. Права Сторон") == (1, "Права Сторон")
    # Already-doubled text collapses to a single clean paragraph.
    assert split_leading_number("1.1. 1.1. По настоящему Договору") == (2, "По настоящему Договору")


def test_ordinary_text_is_not_mistaken_for_a_number() -> None:
    for text in (
        "1 000 000 тенге подлежат оплате в течение 5 рабочих дней.",
        "10.05.2026 стороны подписали акт приёма-передачи.",
        "10.05.2026. Стороны подписали акт приёма-передачи.",
        "Услуги оказываются по адресу: г. Алматы, ул. Абая, 15.",
    ):
        assert split_leading_number(text) == (0, text)


def test_model_numbers_are_stripped_at_the_model_boundary() -> None:
    draft = _draft_from(_DEFECTIVE_PAYLOAD)
    assert draft.sections[0].heading == "Предмет Договора"
    assert draft.sections[0].clauses[0].text == "По настоящему Договору Исполнитель обязуется оказать услуги."
    for line in draft.body_lines():
        assert not re.match(r"^\d", line), line


def test_flat_third_level_clause_becomes_a_subclause() -> None:
    draft = _draft_from(_DEFECTIVE_PAYLOAD)
    responsibility = draft.sections[1]
    assert len(responsibility.clauses) == 1
    assert responsibility.clauses[0].subclauses == [
        "Заказчик отвечает за достоверность переданных сведений.",
        "Исполнитель отвечает за качество услуг.",
    ]


def test_numbering_is_generated_once_per_paragraph() -> None:
    draft = _draft_from(_DEFECTIVE_PAYLOAD)
    numbered = iter_numbered_paragraphs(draft.sections)
    assert numbered[0] == ("1.", "Предмет Договора", 0)
    assert numbered[1][0] == "1.1."
    assert numbered[3] == ("2.", "Ответственность Сторон", 0)
    assert numbered[4][0] == "2.1."
    assert numbered[5][0] == "2.1.1."
    assert numbered[6][0] == "2.1.2."


def test_docx_never_renders_a_duplicated_number() -> None:
    lines = _docx_lines(_draft_from(_DEFECTIVE_PAYLOAD))
    doubled = re.compile(r"^\s*\d+(?:\.\d+)*\.\s+\d+(?:\.\d+)*\.")
    assert not [line for line in lines if doubled.match(line)]
    assert "1. Предмет Договора" in lines
    assert "1.1. По настоящему Договору Исполнитель обязуется оказать услуги." in lines
    assert "2.1.1. Заказчик отвечает за достоверность переданных сведений." in lines


def test_preamble_defects_flag_a_missing_identification_block() -> None:
    assert preamble_defects([])
    assert preamble_defects(["совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем."])
    assert not preamble_defects([
        "ТОО «Астана Логистик», именуемое в дальнейшем «Заказчик», в лице директора Иванова И.И., "
        "действующего на основании Устава, с одной стороны, и ИП Сериков А.Б., именуемый в дальнейшем "
        "«Исполнитель», действующий на основании свидетельства о государственной регистрации ИП "
        "№ 123 от 01.02.2020, с другой стороны, совместно именуемые «Стороны», а по отдельности — "
        "«Сторона», заключили настоящий Договор о нижеследующем."
    ])


def test_export_inserts_the_identification_block_when_the_model_omits_it() -> None:
    restored = ensure_identified_preamble(
        ["совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем."],
        party_a=["ТОО «Астана Логистик», БИН 123456789012"],
        party_b=["ИП Сериков А.Б., ИИН 900101300123"],
    )
    # The bare closing stub is replaced, not duplicated.
    assert len(restored) == 1
    text = restored[0]
    assert "ТОО «Астана Логистик», БИН 123456789012" in text
    assert "ИП Сериков А.Б., ИИН 900101300123" in text
    assert text.count("в дальнейшем") == 2
    assert text.count("на основании") == 2
    assert text.count("совместно именуемые «Стороны»") == 1
    assert not preamble_defects(restored)


def test_docx_preamble_precedes_the_first_section_and_is_marked_preliminary() -> None:
    lines = _docx_lines(_draft_from(_DEFECTIVE_PAYLOAD))
    preamble_index = next(i for i, line in enumerate(lines) if "в дальнейшем" in line)
    first_section_index = lines.index("1. Предмет Договора")
    assert preamble_index < first_section_index
    assert "на основании" in lines[preamble_index]
    assert "KORGAN QA STATUS: PRELIMINARY DRAFT" in lines


def test_a_complete_preamble_is_left_untouched() -> None:
    payload = dict(_DEFECTIVE_PAYLOAD)
    payload["preamble"] = [
        "ТОО «Астана Логистик», БИН 123456789012, именуемое в дальнейшем «Заказчик», в лице директора "
        "Иванова И.И., действующего на основании Устава, с одной стороны, и ИП Сериков А.Б., ИИН "
        "900101300123, именуемый в дальнейшем «Исполнитель», действующий на основании свидетельства о "
        "государственной регистрации ИП № 123 от 01.02.2020, с другой стороны, совместно именуемые "
        "«Стороны», а по отдельности — «Сторона», заключили настоящий Договор о нижеследующем."
    ]
    lines = _docx_lines(_draft_from(payload))
    assert payload["preamble"][0] in lines
    assert "[ТРЕБУЕТ УТОЧНЕНИЯ" not in "\n".join(lines)


def test_plain_string_clauses_stay_supported() -> None:
    section = ContractSection("2. Порядок оплаты", ["2.1. Оплата производится в течение 5 дней."])
    assert section.heading == "Порядок оплаты"
    assert section.clauses[0].text == "Оплата производится в течение 5 дней."
    assert section.clauses[0].subclauses == []
