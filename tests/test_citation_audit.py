"""Tests for the per-citation post-processing audit and the text-integrity gate."""

from __future__ import annotations

from korgan.citation_audit import CitationVerdict, audit_citations
from korgan.document_release import LAW_CHECK_NOTE_PREFIX, review_document
from korgan.provision_corpus import corpus_checked_on, lookup
from korgan.text_integrity import integrity_findings, is_intact

_CORPUS_QUOTE = "Отзыв представляется не позднее десяти рабочих дней со дня получения копии иска."


def test_corpus_holds_the_current_wording_of_article_166_part_2() -> None:
    record = lookup("ГПК РК", "166", "2")
    assert record is not None
    assert "десяти рабочих дней" in record.text
    # Not read from the official source in this environment, so it is REPORTED.
    assert not record.citable_verbatim


def test_repealed_wording_quoted_verbatim_is_rejected() -> None:
    """The defect from document #3: an old edition quoted inside quotation marks."""
    text = (
        "Согласно части 2 статьи 166 ГПК РК «отзыв представляется в установленный судом срок, "
        "обеспечивающий возможность ознакомления с ним до начала судебного заседания»."
    )
    audit = audit_citations(text)
    assert len(audit.findings) == 1
    assert audit.findings[0].verdict is CitationVerdict.QUOTE_MISMATCH
    assert audit.blocking


def test_partial_overlap_is_not_accepted_as_a_match() -> None:
    text = (
        "В соответствии с частью 2 статьи 166 ГПК РК «отзыв представляется не позднее десяти "
        "рабочих дней»."
    )
    audit = audit_citations(text)
    assert audit.findings[0].verdict is CitationVerdict.QUOTE_MISMATCH


def test_matching_quote_from_an_unverified_record_needs_a_visible_marker() -> None:
    without_marker = f"Согласно части 2 статьи 166 ГПК РК «{_CORPUS_QUOTE}»"
    assert audit_citations(without_marker).findings[0].verdict is CitationVerdict.QUOTE_MISMATCH

    with_marker = (
        f"[ТРЕБУЕТ ПРОВЕРКИ: согласно части 2 статьи 166 ГПК РК «{_CORPUS_QUOTE}» — "
        "формулировка подлежит сверке по официальному источнику]"
    )
    finding = audit_citations(with_marker).findings[0]
    assert finding.verdict is CitationVerdict.UNVERIFIED_SOURCE
    assert not finding.blocks_release


def test_provision_absent_from_the_corpus_may_not_be_asserted() -> None:
    text = "В силу статьи 953 ГК РК моральный вред возмещается в денежной форме независимо от вины."
    finding = audit_citations(text).findings[0]
    assert finding.verdict is CitationVerdict.UNVERIFIABLE
    assert finding.blocks_release


def test_naming_an_unverifiable_article_without_asserting_content_is_allowed() -> None:
    text = (
        "[ТРЕБУЕТ ПРОВЕРКИ: применимость статьи 960 ГК РК и её действующая редакция подлежат сверке "
        "по официальному источнику до подачи документа]"
    )
    finding = audit_citations(text).findings[0]
    assert finding.verdict is CitationVerdict.UNVERIFIED_SOURCE
    assert not finding.blocks_release


def test_non_legal_numbering_is_not_treated_as_a_citation() -> None:
    text = "Согласно пункту 3 настоящего Договора Стороны согласовали порядок приёмки."
    assert not audit_citations(text).findings


def test_every_citation_is_checked_separately_in_one_document() -> None:
    """Documents mixed accurate and inaccurate citations — each is judged alone."""
    text = (
        f"[ТРЕБУЕТ ПРОВЕРКИ: часть 2 статьи 166 ГПК РК «{_CORPUS_QUOTE}» — подлежит сверке]\n"
        "Согласно статье 953 ГК РК моральный вред возмещается в денежной форме.\n"
        "На основании статьи 665 Налогового кодекса РК государственная пошлина составляет 1 процент."
    )
    audit = audit_citations(text)
    verdicts = {f"{f.act} {f.article}": f.verdict for f in audit.findings}
    assert verdicts["ГПК РК 166"] is CitationVerdict.UNVERIFIED_SOURCE
    assert verdicts["ГК РК 953"] is CitationVerdict.UNVERIFIABLE
    assert verdicts["НК РК 665"] is CitationVerdict.UNVERIFIABLE
    assert len(audit.blocking) == 2


def test_hyphenated_article_number_is_preserved_for_lookup(monkeypatch) -> None:
    looked_up: list[tuple[str, str, str]] = []

    def capture_lookup(act: str, article: str, part: str):
        looked_up.append((act, article, part))
        return None

    monkeypatch.setattr("korgan.citation_audit.lookup", capture_lookup)
    audit_citations("Согласно статье 353-1 ГК РК требование подлежит проверке.")
    assert looked_up == [("ГК РК", "353-1", "")]


def test_same_reference_is_deduplicated_only_within_one_paragraph() -> None:
    same_paragraph = "Статья 953 ГК РК; статья 953 ГК РК."
    separate_paragraphs = "Статья 953 ГК РК.\nСтатья 953 ГК РК."

    assert len(audit_citations(same_paragraph).findings) == 1
    assert len(audit_citations(separate_paragraphs).findings) == 2


def test_glued_fragment_after_a_closing_quote_is_detected() -> None:
    """The reported artefact: «...не предусмотрено иное».евидно"""
    broken = "Стороны согласовали, что иное не предусмотрено».евидно, что требование заявлено."
    findings = integrity_findings(broken)
    assert any(finding.code == "closing_quote_glued" for finding in findings)
    assert not is_intact(broken)


def test_clean_legal_russian_passes_the_integrity_check() -> None:
    clean = (
        "Согласно пункту 1 статьи 272 ГК РК обязательства должны исполняться надлежащим образом. "
        "Ответчик, т.е. индивидуальный предприниматель, оплату не произвёл. "
        "Сумма долга составляет 1 200 000 тенге, т.д. и т.п. не применяются."
    )
    assert is_intact(clean), integrity_findings(clean)


def test_unbalanced_quotes_are_detected() -> None:
    assert not is_intact("Суд указал: «обязательство подлежит исполнению")


def test_release_gate_always_adds_the_law_verification_item() -> None:
    text = "Согласно статье 272 ГК РК обязательства исполняются надлежащим образом."
    report = review_document(text)
    assert report.cites_law
    checklist = report.checklist(["Уточнить сумму долга."])
    assert checklist[0] == "Уточнить сумму долга."
    assert any(item.startswith(LAW_CHECK_NOTE_PREFIX) for item in checklist)


def test_law_verification_item_states_the_corpus_provenance() -> None:
    note = next(
        item for item in review_document("статья 272 ГК РК").checklist() if item.startswith(LAW_CHECK_NOTE_PREFIX)
    )
    if corpus_checked_on():
        assert corpus_checked_on() in note
    else:
        assert "не проводилась" in note


def test_document_without_citations_gets_no_law_item() -> None:
    report = review_document("Стороны согласовали порядок приёмки услуг в Приложении № 1.")
    assert not report.cites_law
    assert report.checklist(["Уточнить срок оплаты."]) == ["Уточнить срок оплаты."]
