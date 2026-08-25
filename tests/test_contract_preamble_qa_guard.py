from __future__ import annotations

from types import SimpleNamespace

from korgan.contract_preamble_qa_guard import canonicalize_contract_preamble


def test_duplicate_specialized_and_universal_preamble_collapses_to_client_specific_one() -> None:
    specialized = (
        "ТОО «ТехПром Снаб», именуемое в дальнейшем «Поставщик», в лице директора "
        "[ТРЕБУЕТ УТОЧНЕНИЯ: ФИО], действующего на основании Устава, с одной стороны, и "
        "ТОО «Альфа Строй KZ», именуемое в дальнейшем «Покупатель», в лице директора "
        "[ТРЕБУЕТ УТОЧНЕНИЯ: ФИО], действующего на основании Устава, с другой стороны, "
        "совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем."
    )
    generic = (
        "[Организационно-правовая форма и полное наименование], именуемое(-ый) в дальнейшем "
        "«[роль по договору]», в лице [должность] [фамилия, имя, отчество], действующего на основании "
        "[устава / доверенности № и дата], с одной стороны, и [вторая сторона в том же формате], "
        "с другой стороны, совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем."
    )
    draft = SimpleNamespace(preamble=[specialized, generic])

    changed = canonicalize_contract_preamble(draft)

    assert changed is True
    assert draft.preamble == [specialized]


def test_split_substantive_preamble_is_not_destroyed() -> None:
    draft = SimpleNamespace(
        preamble=[
            "ТОО «Поставщик», именуемое в дальнейшем «Поставщик», в лице директора А.А., действующего на основании Устава, с одной стороны,",
            "ТОО «Покупатель», именуемое в дальнейшем «Покупатель», в лице директора Б.Б., действующего на основании Устава, с другой стороны, совместно именуемые «Стороны», заключили настоящий Договор.",
        ]
    )

    changed = canonicalize_contract_preamble(draft)

    assert changed is False
    assert len(draft.preamble) == 2
