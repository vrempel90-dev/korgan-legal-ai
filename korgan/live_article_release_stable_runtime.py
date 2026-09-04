"""Stable final article verification for production document release.

The legal corpus is refreshed from allowlisted Ministry of Justice sources in the
background and lives on a persistent Railway volume. Re-fetching the same whole
acts from Adilet for every generated Word made document delivery depend on a
second, fragile network round-trip after drafting had already completed.

This runtime keeps the strict wording/article checks from
``live_article_release_runtime`` but changes two production details:

1. prefer the already source-validated persistent corpus and use the live
   network verifier only when that act is absent or untrusted;
2. for a paraphrase, verify the sentence that actually owns the citation rather
   than unrelated factual/legal sentences that happen to share the same DOCX
   paragraph.

A missing article, wrong quotation or proposition drift still fails closed. A
transient Adilet/TLS outage or an unrelated sentence in the same paragraph no
longer turns an otherwise valid document into a false error at 95% generation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from korgan import live_article_release_runtime as runtime
from korgan.legal import pipeline
from korgan.legal.official_sources import is_allowed_adilet_url, is_allowed_zan_pdf_url

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_NETWORK_LIVE_ACT = runtime._live_act
_ORIGINAL_CITATION_PARAGRAPH = runtime._citation_paragraph

# A full stop inside an abbreviation such as ``ст. 9`` is followed by a digit,
# so it is deliberately not a boundary. A semicolon is always a safe clause
# boundary for this purpose. Exact quoted provisions are never narrowed.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=;)\s+|(?<=[.!?])\s+(?=[А-ЯЁA-Z«])")


def _official_source_for_act(url: str, act_id: str) -> bool:
    return is_allowed_adilet_url(url, act_id=act_id) or is_allowed_zan_pdf_url(url, act_id=act_id)


def _reference_in_statement(statement: str, reference: Any) -> bool:
    """Whether this statement contains the exact act/article/part reference."""
    for match in runtime.citation_audit._REFERENCE_RE.finditer(statement or ""):
        article = match.group("article")
        part = (match.group("part") or "").strip()
        window = match.group(0) + " " + statement
        act = runtime.citation_audit._detect_act(window)
        candidate = runtime.citation_audit.ProvisionReference(act, article, part)
        if reference.matches(candidate):
            return True
    return False


def _citation_statement(text: str, reference: Any) -> str:
    """Return the sentence that owns a paraphrased citation.

    The original verifier used the whole DOCX paragraph. Production paragraphs
    often contain several independent sentences: one states the legal rule and
    cites an article, the next applies a contract term, amount, deadline or
    remedy to the facts. Feeding both sentences to ``paraphrase_defects`` made
    those factual/application terms look as if the cited article had to contain
    every one of them.

    Exact quotations stay paragraph-scoped so quote extraction is unchanged.
    If sentence localisation is ambiguous, we also keep the original paragraph
    and therefore retain the previous fail-closed behaviour.
    """
    paragraph = _ORIGINAL_CITATION_PARAGRAPH(text, reference)
    if not paragraph:
        return ""
    if runtime.citation_audit._quote_in(paragraph):
        return paragraph

    statements = [part.strip() for part in _SENTENCE_SPLIT_RE.split(paragraph) if part.strip()]
    if len(statements) <= 1:
        return paragraph

    matches = [statement for statement in statements if _reference_in_statement(statement, reference)]
    if len(matches) != 1:
        return paragraph

    statement = matches[0]
    LOGGER.info(
        "LIVE_ARTICLE_SENTENCE_SCOPE reference=%s paragraph_chars=%d statement_chars=%d",
        reference.label(),
        len(paragraph),
        len(statement),
    )
    return statement


def load_official_corpus_act(act_id: str) -> runtime.LiveAct | None:
    """Build a ``LiveAct`` from the persistent source-validated corpus.

    The corpus loader has already bound the act identity to a fixed official
    Adilet/ZAN URL and stored exact provisions. We deliberately reject rows
    whose act-level provenance is not one of those allowlisted official URLs.
    """

    corpus = pipeline.open_corpus()
    if corpus is None:
        return None

    try:
        act_row = corpus.connection.execute(
            "SELECT url, edition_date, loaded_at FROM acts WHERE act_id = ?",
            (act_id,),
        ).fetchone()
        if act_row is None:
            return None

        source_url = str(act_row["url"] or "").strip()
        if not _official_source_for_act(source_url, act_id):
            LOGGER.error(
                "LIVE_ARTICLE_CORPUS_REJECTED act_id=%s reason=untrusted_provenance source=%s",
                act_id,
                source_url,
            )
            return None

        rows = corpus.connection.execute(
            "SELECT article_no, item_no, heading, body FROM provisions "
            "WHERE act_id = ? ORDER BY sort_key",
            (act_id,),
        ).fetchall()
        if not rows:
            return None

        articles: dict[str, dict[str, str]] = {}
        for row in rows:
            article_no = str(row["article_no"] or "").strip()
            if not article_no:
                continue
            item_no = str(row["item_no"] or "").strip()
            heading = " ".join(str(row["heading"] or "").split()).strip()
            body = " ".join(str(row["body"] or "").split()).strip()
            text = " ".join(part for part in (heading, body) if part).strip()
            if not text:
                continue
            article = articles.setdefault(article_no, {})
            if item_no in article and text not in article[item_no]:
                article[item_no] = (article[item_no] + " " + text).strip()
            else:
                article[item_no] = text

        if not articles:
            return None

        edition_date = str(act_row["edition_date"] or "").strip()
        loaded_at = str(act_row["loaded_at"] or "").strip()
        LOGGER.info(
            "LIVE_ARTICLE_CORPUS_READY act_id=%s articles=%d edition=%s loaded_at=%s source=%s",
            act_id,
            len(articles),
            edition_date or "not_exposed",
            loaded_at or "not_exposed",
            source_url,
        )
        return runtime.LiveAct(
            act_id=act_id,
            source_url=source_url,
            edition_date=edition_date,
            articles=articles,
        )
    except Exception:
        LOGGER.exception("LIVE_ARTICLE_CORPUS_FAILED act_id=%s; falling back to live network", act_id)
        return None
    finally:
        corpus.close()


async def _stable_live_act(act_id: str) -> runtime.LiveAct:
    corpus_act = load_official_corpus_act(act_id)
    if corpus_act is not None:
        return corpus_act
    return await _NETWORK_LIVE_ACT(act_id)


def install_stable_live_article_release_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    runtime._live_act = _stable_live_act  # type: ignore[assignment]
    runtime._citation_paragraph = _citation_statement  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info(
        "Installed stable live article verifier: official corpus first, citation-sentence paraphrase scope"
    )


install_stable_live_article_release_runtime()
