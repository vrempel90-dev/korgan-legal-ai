from __future__ import annotations

from korgan.project_claim_release_hotfix import (
    filter_fatal_release_defects,
    repair_safe_spacing_text,
)


def test_sub_85_and_filing_details_do_not_block_reviewable_project() -> None:
    defects = [
        "финальный юридический quality-gate ниже 8.5 по содержательным причинам",
        "остались нерешённые вопросы проверки: требование о взыскании законной неустойки требует подтверждения",
        "не определена госпошлина или подтвержденная льгота",
        "наименование суда не подтверждено материалами дела или официальным source-bound исследованием",
    ]
    assert filter_fatal_release_defects(defects) == []


def test_missing_verified_material_law_remains_fatal() -> None:
    defects = [
        "не каждое самостоятельное требование имеет собственную VERIFIED правовую опору",
        "отсутствует source-bound VERIFIED правовая основа текущего дела",
        "финальный юридический quality-gate ниже 8.5 по содержательным причинам",
    ]
    assert filter_fatal_release_defects(defects) == [
        "не каждое самостоятельное требование имеет собственную VERIFIED правовую опору",
        "отсутствует source-bound VERIFIED правовая основа текущего дела",
    ]


def test_empty_prayer_and_broken_legal_basis_still_block() -> None:
    defects = [
        "просительная часть пуста после финальной очистки",
        "обнаружено поврежденное правовое основание в судебном тексте",
    ]
    assert filter_fatal_release_defects(defects) == defects


def test_safe_missing_space_after_sentence_is_repaired() -> None:
    assert repair_safe_spacing_text("Долг составляет 4 025 000 тенге.Взыскать долг.") == (
        "Долг составляет 4 025 000 тенге. Взыскать долг."
    )


def test_lowercase_weld_is_not_silently_repaired() -> None:
    broken = "обязательство исполнено.евидно нарушение"
    assert repair_safe_spacing_text(broken) == broken
