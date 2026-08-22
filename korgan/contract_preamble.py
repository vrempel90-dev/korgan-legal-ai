"""Preamble integrity for KZ contracts.

Kazakhstan business practice requires the opening paragraph to identify both
parties, the person signing for each of them and the instrument that person
acts under (устав, доверенность, свидетельство о государственной регистрации
ИП). A contract that jumps straight from the date to "совместно именуемые
«Стороны», заключили настоящий Договор" is defective even when the requisites
appear at the bottom of the document.

This module is the shared definition of that rule: the drafting QA loop uses it
to send a deficient preamble back to the model, and the .docx export uses it as
a last-resort guarantee that the identification block is physically present.
"""

from __future__ import annotations

PREAMBLE_CLOSING = (
    "совместно именуемые «Стороны», а по отдельности — «Сторона», "
    "заключили настоящий Договор о нижеследующем."
)

PREAMBLE_TEMPLATE = (
    "[Организационно-правовая форма и полное наименование], именуемое(-ый) в дальнейшем "
    "«[роль по договору]», в лице [должность] [фамилия, имя, отчество], действующего на основании "
    "[устава / доверенности № и дата / свидетельства о государственной регистрации ИП № и дата], "
    "с одной стороны, и [вторая сторона в том же формате], с другой стороны, " + PREAMBLE_CLOSING
)

_UNKNOWN_PARTY = (
    "[ТРЕБУЕТ УТОЧНЕНИЯ: организационно-правовая форма, полное наименование и БИН/ИИН {label}]"
)
_UNKNOWN_ROLE = "[ТРЕБУЕТ УТОЧНЕНИЯ: наименование стороны по договору]"
_UNKNOWN_SIGNATORY = "[ТРЕБУЕТ УТОЧНЕНИЯ: должность, фамилия, имя, отчество подписанта]"
_UNKNOWN_AUTHORITY = (
    "[ТРЕБУЕТ УТОЧНЕНИЯ: устав / доверенность № и дата / "
    "свидетельство о государственной регистрации индивидуального предпринимателя № и дата]"
)


def _side_block(party: list[str], label: str, side_phrase: str) -> str:
    name = next((str(x).strip() for x in party or [] if str(x).strip()), "")
    if not name:
        name = _UNKNOWN_PARTY.format(label=label)
    return (
        f"{name}, именуемое(-ый) в дальнейшем «{_UNKNOWN_ROLE}», "
        f"в лице {_UNKNOWN_SIGNATORY}, действующего на основании {_UNKNOWN_AUTHORITY}, "
        f"{side_phrase}"
    )


def placeholder_preamble(party_a: list[str], party_b: list[str]) -> str:
    """The full identification paragraph with visible gaps where data is missing."""
    return " ".join(
        [
            _side_block(party_a, "Стороны 1", "с одной стороны, и"),
            _side_block(party_b, "Стороны 2", "с другой стороны,"),
            PREAMBLE_CLOSING,
        ]
    )


def preamble_defects(preamble: list[str]) -> list[str]:
    """Return the QA findings for a contract preamble (empty list = passes)."""
    text = " ".join(str(x) for x in preamble or []).strip().lower()
    if not text:
        return [
            "преамбула отсутствует: нет вводного абзаца, идентифицирующего обе стороны, "
            "их роли по договору и основания полномочий подписантов"
        ]

    defects: list[str] = []
    if text.count("в дальнейшем") < 2:
        defects.append(
            "преамбула не содержит полной идентификации обеих сторон: у каждой стороны должны быть "
            "указаны организационно-правовая форма/наименование и роль по договору "
            "(«именуемое(-ый) в дальнейшем «...»»)"
        )
    if "на основании" not in text:
        defects.append(
            "преамбула не указывает основание полномочий подписанта каждой стороны "
            "(устав, доверенность, свидетельство о государственной регистрации ИП)"
        )
    if "в лице" not in text:
        defects.append("преамбула не называет лицо, подписывающее договор от каждой стороны")
    if "заключили настоящий" not in text and "заключили договор" not in text:
        defects.append("преамбула не содержит завершающей формулы о заключении договора")
    return defects


def _is_bare_closing(line: str) -> bool:
    """True for the defective stub "…совместно именуемые «Стороны», заключили…".

    Such a line carries the closing formula but none of the identification, so
    it is replaced rather than kept alongside the generated block.
    """
    lowered = str(line).lower()
    if "совместно именуем" not in lowered:
        return False
    return "в лице" not in lowered and "на основании" not in lowered


def ensure_identified_preamble(
    preamble: list[str],
    *,
    party_a: list[str],
    party_b: list[str],
) -> list[str]:
    """Guarantee that the rendered preamble opens with the identification block."""
    if not preamble_defects(preamble):
        return [str(x) for x in preamble]

    remainder = [str(x) for x in preamble or [] if str(x).strip() and not _is_bare_closing(x)]
    return [placeholder_preamble(party_a, party_b), *remainder]
