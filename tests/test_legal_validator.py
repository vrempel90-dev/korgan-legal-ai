"""Блок 2: валидатор цитат — в документ попадают только подтверждённые нормы."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.corpus import ACT_GK_SPECIAL, LegalCorpus, make_article_id  # noqa: E402
from korgan.legal.validator import (  # noqa: E402
    LAWYER_REVIEW_MARKER,
    LEGAL_BASIS_SCHEMA,
    REASON_EMPTY_THESIS,
    REASON_MALFORMED,
    REASON_NOT_OFFERED,
    REASON_UNKNOWN_ID,
    build_offer,
    find_unvalidated_citations,
    scan_text_citations,
    validate_blocks,
)
from scripts.load_corpus import load_act  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUS_URL = "https://adilet.zan.kz/rus/docs/K990000409_"

ID_621_2 = make_article_id(ACT_GK_SPECIAL, "621", "2")
ID_630_2 = make_article_id(ACT_GK_SPECIAL, "630", "2")
ID_683 = make_article_id(ACT_GK_SPECIAL, "683")
ID_MISSING = make_article_id(ACT_GK_SPECIAL, "9999")


@pytest.fixture()
def corpus(tmp_path: Path) -> LegalCorpus:
    with LegalCorpus(tmp_path / "corpus.sqlite3") as db:
        html = (FIXTURES / "adilet_gk_osobennaya.html").read_text(encoding="utf-8")
        load_act(db, ACT_GK_SPECIAL, html, url=RUS_URL, edition_date="2026-01-01")
        yield db


def _block(article_id: str, thesis: str = "заказчик вправе требовать возврата аванса", link: str = "") -> dict:
    return {"article_id": article_id, "thesis": thesis, "link_to_facts": link}


def test_schema_requires_block_fields() -> None:
    item = LEGAL_BASIS_SCHEMA["properties"]["legal_basis"]["items"]

    assert item["required"] == ["article_id", "thesis", "link_to_facts"]
    assert item["additionalProperties"] is False
    assert LEGAL_BASIS_SCHEMA["additionalProperties"] is False


def test_offered_and_existing_block_is_accepted(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_630_2)], {ID_630_2}, corpus)

    assert result.is_clean
    assert len(result.accepted) == 1
    assert result.accepted[0].provision.article_no == "630"


def test_block_outside_the_offered_set_is_rejected(corpus: LegalCorpus) -> None:
    """Норма существует в корпусе, но модели её не предлагали."""
    result = validate_blocks([_block(ID_683)], {ID_630_2}, corpus)

    assert not result.is_clean
    assert result.rejected[0].reason == REASON_NOT_OFFERED
    assert result.accepted == []


def test_block_with_unknown_id_is_rejected(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_MISSING)], {ID_MISSING}, corpus)

    assert result.rejected[0].reason == REASON_UNKNOWN_ID


def test_block_without_thesis_is_rejected(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_630_2, thesis="  ")], {ID_630_2}, corpus)

    assert result.rejected[0].reason == REASON_EMPTY_THESIS


def test_block_without_article_id_is_rejected(corpus: LegalCorpus) -> None:
    result = validate_blocks([{"thesis": "что-то", "link_to_facts": ""}], set(), corpus)

    assert result.rejected[0].reason == REASON_MALFORMED
    assert result.rejected[0].article_id == "(пусто)"


def test_rejected_block_becomes_a_visible_marker(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_630_2), _block(ID_MISSING)], {ID_630_2, ID_MISSING}, corpus)

    lines = result.legal_basis_lines()

    assert len(lines) == 2
    assert LAWYER_REVIEW_MARKER in lines[1]
    assert LAWYER_REVIEW_MARKER not in lines[0]


def test_accepted_block_renders_provision_and_link(corpus: LegalCorpus) -> None:
    result = validate_blocks(
        [_block(ID_630_2, link="Ответчик работы не выполнил, аванс не возвращён")],
        {ID_630_2},
        corpus,
    )

    line = result.legal_basis_lines()[0]

    assert line.startswith("В соответствии со ст. 630")
    assert "п. 2" in line
    assert line.endswith("аванс не возвращён.")


def test_validated_articles_lists_only_accepted(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_630_2), _block(ID_MISSING)], {ID_630_2, ID_MISSING}, corpus)

    assert result.validated_articles() == {"630"}


def test_rejection_notes_name_the_article_id(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_MISSING)], {ID_MISSING}, corpus)

    assert ID_MISSING in result.rejection_notes()[0]


# --- скан финального текста --------------------------------------------------


def test_scan_finds_articles_in_prose() -> None:
    text = "Согласно ст. 630 ГК РК и статьям 715 и 722 ГК РК, а также статье 353 ГК РК."

    assert scan_text_citations(text) == ["630", "715", "722", "353"]


def test_scan_handles_text_without_citations() -> None:
    assert scan_text_citations("Ответчик долг не вернул.") == []


def test_unvalidated_citation_in_thesis_is_caught(corpus: LegalCorpus) -> None:
    """Схема соблюдена, но в тезисе протащена чужая статья."""
    result = validate_blocks(
        [_block(ID_630_2, thesis="применяется также статья 715 ГК РК")],
        {ID_630_2},
        corpus,
    )

    text = "\n".join(result.legal_basis_lines())

    assert result.is_clean
    assert find_unvalidated_citations(text, result) == ["715"]


def test_text_citing_only_validated_articles_is_clean(corpus: LegalCorpus) -> None:
    result = validate_blocks([_block(ID_630_2)], {ID_630_2}, corpus)

    text = "\n".join(result.legal_basis_lines())

    assert find_unvalidated_citations(text, result) == []


def test_build_offer_returns_ids_and_prompt_block(corpus: LegalCorpus) -> None:
    provisions = corpus.search("предоплата подряд возврат")

    offered_ids, prompt_block = build_offer(provisions)

    assert offered_ids
    assert all(corpus.exists(article_id) for article_id in offered_ids)
    assert "article_id:" in prompt_block
    assert "Текст:" in prompt_block
