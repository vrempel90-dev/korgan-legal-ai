from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from docx import Document
from fastapi import HTTPException

from korgan import citation_audit
from korgan import miniapp_api_v2 as core
from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_LABOR,
    ACT_TAX_DUTY,
)
from korgan.legal.corpus_refresh import fetch_adilet
from korgan.provision_check import _norm_claim_only, paraphrase_defects
from korgan.provision_corpus import normalize_text
from scripts.load_corpus import act_url, parse_provisions, strip_html

LOGGER = logging.getLogger(__name__)

FLAG_ENV = "KORGAN_LIVE_ARTICLE_VERIFY"
_CACHE_SECONDS = 60 * 30
_INSTALLED = False
_ORIGINAL_GENERATE = core._generate

# Civil-document production currently owns these official acts. A citation to a
# different statute is not guessed: source-bound AI research may discover it,
# but filing release remains blocked until KORGAN has a deterministic live
# verifier for that act as well.
_ACT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ГПК РК": (ACT_GPK,),
    "ГК РК": (ACT_GK_GENERAL, ACT_GK_SPECIAL),
    "НК РК": (ACT_TAX_DUTY,),
    "ТК РК": (ACT_LABOR,),
    "ЗПП РК": (ACT_CONSUMER,),
}

_EDITION_RE = re.compile(r"Дата\s+редакции\s+(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)


@dataclass(frozen=True)
class LiveAct:
    act_id: str
    source_url: str
    edition_date: str
    articles: dict[str, dict[str, str]]


_CACHE: dict[str, tuple[float, LiveAct]] = {}


class LiveArticleVerificationError(RuntimeError):
    pass


def live_article_verification_enabled() -> bool:
    return str(os.getenv(FLAG_ENV, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _docx_text(file_bytes: bytes) -> str:
    document = Document(io.BytesIO(file_bytes))
    chunks: list[str] = []
    for paragraph in document.paragraphs:
        text = " ".join(str(paragraph.text or "").split()).strip()
        if text:
            chunks.append(text)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                text = " ".join(str(cell.text or "").split()).strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks)


def _build_live_act(act_id: str, html: str, source_url: str) -> LiveAct:
    text = strip_html(html)
    parsed = parse_provisions(text)
    if not parsed:
        raise LiveArticleVerificationError(f"официальный акт {act_id} не содержит распознаваемых статей")

    articles: dict[str, dict[str, str]] = {}
    for item in parsed:
        article = articles.setdefault(item.article_no, {})
        key = str(item.item_no or "")
        body = " ".join(f"{item.heading} {item.body}".split()).strip()
        if key in article and body not in article[key]:
            article[key] = (article[key] + " " + body).strip()
        else:
            article[key] = body

    edition = ""
    match = _EDITION_RE.search(text)
    if match:
        edition = match.group(1)
    return LiveAct(act_id=act_id, source_url=source_url, edition_date=edition, articles=articles)


async def _live_act(act_id: str) -> LiveAct:
    cached = _CACHE.get(act_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] <= _CACHE_SECONDS:
        return cached[1]

    url = act_url(act_id)

    def fetch() -> LiveAct:
        html, final_url = fetch_adilet(url, timeout=35)
        return _build_live_act(act_id, html, final_url)

    try:
        act = await asyncio.to_thread(fetch)
    except Exception as exc:
        raise LiveArticleVerificationError(
            f"не удалось открыть актуальную официальную редакцию {act_id} на Adilet"
        ) from exc
    _CACHE[act_id] = (now, act)
    return act


def _article_text(act: LiveAct, article: str, part: str) -> str:
    items = act.articles.get(article)
    if not items:
        return ""
    if part:
        exact = items.get(part)
        if exact:
            return exact
        # Some one-part articles are not split by the parser because the only
        # numbered paragraph is also the entire body. Only part 1 may safely
        # fall back to the whole single entry.
        if part == "1" and len(items) == 1 and "" in items:
            return items[""]
        return ""
    return " ".join(value for value in items.values() if value).strip()


def _citation_paragraph(text: str, reference: citation_audit.ProvisionReference) -> str:
    for match in citation_audit._REFERENCE_RE.finditer(text or ""):
        article = match.group("article")
        part = (match.group("part") or "").strip()
        window = match.group(0) + " " + citation_audit._paragraph_around(text, match.start())
        act = citation_audit._detect_act(window)
        candidate = citation_audit.ProvisionReference(act, article, part)
        if reference.matches(candidate):
            return citation_audit._paragraph_around(text, match.start())
    return ""


def _verify_wording(paragraph: str, live_text: str, reference: citation_audit.ProvisionReference) -> None:
    quote = citation_audit._quote_in(paragraph)
    if quote:
        if normalize_text(quote) not in normalize_text(live_text):
            raise LiveArticleVerificationError(
                f"дословная цитата {reference.label()} не совпадает с живым текстом Adilet"
            )
        return

    legal_statement = _norm_claim_only(paragraph)
    defects = paraphrase_defects(legal_statement, live_text)
    if defects:
        raise LiveArticleVerificationError(
            f"правовой вывод по {reference.label()} не подтверждается живым текстом нормы: {defects[0]}"
        )


async def verify_document_articles(file_bytes: bytes) -> None:
    text = _docx_text(file_bytes)
    references = citation_audit.extract_references(text)
    if not references:
        return

    for reference in references:
        candidates = _ACT_CANDIDATES.get(reference.act)
        if not candidates:
            raise LiveArticleVerificationError(
                f"для {reference.label()} нет детерминированного live-verifier; ссылка не выпускается"
            )

        matches: list[tuple[LiveAct, str]] = []
        for act_id in candidates:
            live = await _live_act(act_id)
            provision = _article_text(live, reference.article, reference.part)
            if provision:
                matches.append((live, provision))

        if len(matches) != 1:
            if not matches:
                raise LiveArticleVerificationError(
                    f"{reference.label()} не найдена в актуальном официальном тексте Adilet"
                )
            raise LiveArticleVerificationError(
                f"{reference.label()} неоднозначно сопоставилась с несколькими актуальными актами"
            )

        live, provision = matches[0]
        paragraph = _citation_paragraph(text, reference)
        if not paragraph:
            raise LiveArticleVerificationError(f"не удалось локализовать {reference.label()} в финальном Word")
        _verify_wording(paragraph, provision, reference)
        LOGGER.info(
            "LIVE_ARTICLE_VERIFIED reference=%s act_id=%s edition=%s source=%s",
            reference.label(),
            live.act_id,
            live.edition_date or "not_exposed",
            live.source_url,
        )


async def _guarded_generate(document_type: str, context: str, language: str) -> tuple[Any, bytes, str, dict[str, Any]]:
    draft, file_bytes, filename, meta = await _ORIGINAL_GENERATE(document_type, context, language)
    if not live_article_verification_enabled():
        return draft, file_bytes, filename, meta

    try:
        await verify_document_articles(file_bytes)
    except LiveArticleVerificationError as exc:
        # Generation jobs consume the payment only after _generate returns.
        # Therefore a temporary source outage or a mismatched article keeps the
        # paid order approved and retryable instead of charging for a bad Word.
        raise HTTPException(
            status_code=422,
            detail=(
                "KORGAN не выпустил документ: статья или её содержание не прошли "
                "повторную live-проверку по актуальной официальной редакции Adilet. "
                "Повторно платить не нужно. " + str(exc)
            ),
        ) from exc
    return draft, file_bytes, filename, meta


def install_live_article_release_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    core._generate = _guarded_generate  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info(
        "Installed live article release runtime enabled=%s",
        live_article_verification_enabled(),
    )


install_live_article_release_runtime()
