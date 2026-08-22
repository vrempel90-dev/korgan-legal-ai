from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_LABOR,
    ACT_TAX_DUTY,
)
from korgan.legal.pipeline import local_corpus_enabled, open_corpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.provision_check import paraphrase_defects

FILING_ACTION_PREFIX = "FILING_ACTION: "
LEGAL_GROUNDING_PREFIX = "LEGAL_GROUNDING: "
LEGAL_CORRECTION_PREFIX = "LEGAL_CORRECTION: "

_VERIFIED_LINE_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*"
    r"текст\s+нормы:\s*«(?P<quote>.*?)»;\s*источник:\s*(?P<source>.*?)\]\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_RE = re.compile(r"(?:статья|статьи|ст\.)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_ARTICLE_REPLACE_RE = re.compile(r"((?:статья|статьи|ст\.)\s*)\d+(?:-\d+)?", re.IGNORECASE)
_PART_RE = re.compile(r"(?:част[ьи]|пункт|п\.)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_INTERNAL_MARKER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ\s+(?:ПРОВЕРКИ|УТОЧНЕНИЯ|ДОБАВИТЬ)|ТЕКСЕРУ\s+ҚАЖЕТ|НАҚТЫЛАУ\s+ҚАЖЕТ)[^\]]*\]",
    re.IGNORECASE,
)
_LEGAL_ENTITY_RE = re.compile(
    r"(?:\bБИН\b|\bТОО\b|\bАО\b|\bНАО\b|\bРГП\b|\bРГКП\b|\bКГП\b|\bКГКП\b|\bКГУ\b|"
    r"\bГУ\b|\bОЮЛ\b|товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|акционерн\w*\s+обществ\w*)",
    re.IGNORECASE,
)
_IP_RE = re.compile(r"(?:\bИП\b|индивидуальн\w*\s+предпринимател\w*)", re.IGNORECASE)
_BANK_RE = re.compile(r"(?:\bIBAN\b|\bИИК\b|банковск\w*\s+реквизит\w*|\bБИК\b|расчетн\w*\s+счет)", re.IGNORECASE)
_DUTY_PROOF_RE = re.compile(
    r"(?:госпошлин\w*|государственн\w*\s+пошлин\w*).*(?:квитанц\w*|плат[её]ж\w*|чек\w*|документ\w*)|"
    r"(?:квитанц\w*|плат[её]ж\w*|чек\w*|документ\w*).*(?:госпошлин\w*|государственн\w*\s+пошлин\w*)",
    re.IGNORECASE,
)
_REGISTRATION_RE = re.compile(
    r"(?:устав\w*|государственн\w*\s+регистрац\w*|перерегистрац\w*|справк\w*\s+о\s+регистрац\w*|"
    r"свидетельств\w*\s+о\s+регистрац\w*)",
    re.IGNORECASE,
)
_POSITIVE_MONEY_RE = re.compile(r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|тг\b|₸)", re.IGNORECASE)
_ECONOMIC_COURT_RE = re.compile(r"экономическ\w*\s+суд", re.IGNORECASE)
_SPECIAL_JURISDICTION_RE = re.compile(
    r"(?:административн\w*\s+суд|военн\w*\s+суд|суд\s+по\s+делам\s+несовершеннолетн\w*)",
    re.IGNORECASE,
)

_SOURCE_ACT_IDS: tuple[tuple[str, str], ...] = (
    ("K940001000_", ACT_GK_GENERAL),
    ("K990000409_", ACT_GK_SPECIAL),
    ("K1500000377", ACT_GPK),
    ("K2500000214", ACT_TAX_DUTY),
    ("Z100000274_", ACT_CONSUMER),
    ("K1500000414", ACT_LABOR),
)
_REGISTRY_PATH = Path(__file__).resolve().parent / "data" / "court_registry.json"


def _normalized(value: str) -> str:
    value = (value or "").replace("ё", "е").replace("Ё", "Е").lower()
    return re.sub(r"[^0-9a-zа-я]+", "", value)


def _party_text(values: list[str]) -> str:
    return " ".join(str(value or "") for value in values)


def _is_business_subject(values: list[str]) -> bool:
    text = _party_text(values)
    return bool(_LEGAL_ENTITY_RE.search(text) or _IP_RE.search(text))


def _is_legal_entity(values: list[str]) -> bool:
    text = _party_text(values)
    return bool(_LEGAL_ENTITY_RE.search(text)) and not bool(_IP_RE.search(text))


def _claimant_context(case_context: str) -> str:
    text = case_context or ""
    match = re.search(
        r"(?is)(?:истец|талап\s+қоюшы)\s*:\s*(.*?)(?=(?:\n|\s)(?:ответчик|жауапкер)\s*:|\Z)",
        text,
    )
    return match.group(1).strip() if match else text


def _source_act_id(source_url: str) -> str | None:
    lowered = (source_url or "").lower()
    for token, act_id in _SOURCE_ACT_IDS:
        if token.lower() in lowered:
            return act_id
    return None


def _article_number(article: str) -> str:
    match = _ARTICLE_RE.search(article or "")
    return match.group(1) if match else ""


def _part_number(article: str) -> str:
    match = _PART_RE.search(article or "")
    return match.group(1) if match else ""


def _replace_article_number(article: str, article_no: str) -> str:
    return _ARTICLE_REPLACE_RE.sub(lambda match: f"{match.group(1)}{article_no}", article, count=1)


def _quote_matches_body(quote: str, body: str) -> bool:
    quote_norm = _normalized(quote)
    body_norm = _normalized(body)
    if len(quote_norm) < 24 or len(body_norm) < 24:
        return False
    if quote_norm in body_norm:
        return True
    quote_tokens = {token for token in re.findall(r"[0-9a-zа-яё]{4,}", (quote or "").lower())}
    body_tokens = {token for token in re.findall(r"[0-9a-zа-яё]{4,}", (body or "").lower())}
    return bool(quote_tokens) and len(quote_tokens & body_tokens) / len(quote_tokens) >= 0.88


def _rows(corpus: Any, act_id: str, article_no: str | None = None) -> list[dict[str, str]]:
    sql = (
        "SELECT p.article_no, p.item_no, p.heading, p.body, p.url FROM provisions p WHERE p.act_id = ?"
        + (" AND p.article_no = ?" if article_no else "")
        + " ORDER BY p.sort_key, p.item_no"
    )
    params: tuple[str, ...] = (act_id, article_no) if article_no else (act_id,)
    raw_rows = corpus.connection.execute(sql, params).fetchall()
    return [
        {
            "article_no": str(row["article_no"] or ""),
            "item_no": str(row["item_no"] or ""),
            "heading": str(row["heading"] or ""),
            "body": str(row["body"] or ""),
            "url": str(row["url"] or ""),
        }
        for row in raw_rows
    ]


def _actual_text(row: dict[str, str]) -> str:
    return f"{row['heading']} {row['body']}".strip()


def _find_quote_match(
    rows: list[dict[str, str]],
    quote: str,
    statement: str,
    *,
    part_no: str = "",
) -> dict[str, str] | None:
    candidates = [row for row in rows if not part_no or row["item_no"] == part_no]
    if not candidates:
        candidates = rows
    for row in candidates:
        actual = _actual_text(row)
        if _quote_matches_body(quote, actual) and not paraphrase_defects(statement, actual):
            return row
    return None


def _find_unique_correction(
    corpus: Any,
    act_id: str,
    quote: str,
    statement: str,
) -> dict[str, str] | None:
    matches = [
        row
        for row in _rows(corpus, act_id)
        if _quote_matches_body(quote, _actual_text(row)) and not paraphrase_defects(statement, _actual_text(row))
    ]
    article_numbers = {row["article_no"] for row in matches if row["article_no"]}
    if len(article_numbers) != 1:
        return None
    article_no = next(iter(article_numbers))
    return next(row for row in matches if row["article_no"] == article_no)


def _add_note(draft: ClaimDraft, note: str) -> None:
    if note and note not in draft.verification_notes:
        draft.verification_notes.append(note)


def _clean_basis_line(value: str) -> str:
    text = " ".join((value or "").split()).strip()
    return re.sub(r"\.{2,}$", ".", text)


def _ground_legal_basis(research: LegalResearch, draft: ClaimDraft) -> None:
    """Re-bind every filing citation to the local Adilet corpus before DOCX release."""
    if not local_corpus_enabled():
        cleaned: list[str] = []
        for value in draft.legal_basis:
            line = _clean_basis_line(str(value))
            if not line or _INTERNAL_MARKER_RE.search(line):
                if line:
                    _add_note(draft, LEGAL_GROUNDING_PREFIX + "служебная пометка удалена из правового обоснования.")
                continue
            if line not in cleaned:
                cleaned.append(line)
        draft.legal_basis = cleaned
        return

    corpus = open_corpus()
    if corpus is None:
        draft.legal_basis = []
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        _add_note(
            draft,
            LEGAL_GROUNDING_PREFIX
            + "локальный корпус Adilet недоступен; номера статей не выпущены в судебный текст без повторной сверки.",
        )
        return

    accepted: list[str] = []
    rejected: list[str] = []
    try:
        for raw in research.verified_claims:
            line = str(raw or "").strip()
            if not line or "официальный перечень судов" in line.lower():
                continue
            match = _VERIFIED_LINE_RE.match(line)
            if match is None:
                rejected.append("VERIFIED-вывод не содержит проверяемой связки статья + текст нормы + источник")
                continue

            statement = _clean_basis_line(match.group("statement")).rstrip(".")
            article = _clean_basis_line(match.group("article")).rstrip(".")
            quote = match.group("quote").strip()
            source = match.group("source").strip()
            if _INTERNAL_MARKER_RE.search(statement) or _INTERNAL_MARKER_RE.search(article):
                rejected.append("служебная пометка обнаружена внутри правового основания")
                continue

            act_id = _source_act_id(source)
            article_no = _article_number(article)
            if not act_id or not article_no:
                rejected.append(f"не удалось однозначно связать правовое основание с корпусом: {article or 'без статьи'}")
                continue

            article_rows = _rows(corpus, act_id, article_no)
            matched = _find_quote_match(
                article_rows,
                quote,
                statement,
                part_no=_part_number(article),
            )
            rendered_article = article

            if matched is None:
                correction = _find_unique_correction(corpus, act_id, quote, statement)
                if correction is not None and correction["article_no"] != article_no:
                    rendered_article = _replace_article_number(article, correction["article_no"])
                    correction_note = f"{article} -> {rendered_article}; дословный фрагмент однозначно совпал с локальным корпусом Adilet"
                    audit = LEGAL_CORRECTION_PREFIX + correction_note
                    if audit not in research.notes:
                        research.notes.append(audit)
                    matched = correction

            if matched is None:
                rejected.append(
                    f"текст нормы не принадлежит указанной статье {article_no}, а безопасная однозначная коррекция не найдена"
                )
                continue

            rendered = _clean_basis_line(f"{statement}. Правовое основание: {rendered_article}.")
            if rendered not in accepted:
                accepted.append(rendered)
    finally:
        corpus.close()

    draft.legal_basis = accepted
    for reason in list(dict.fromkeys(rejected))[:8]:
        _add_note(draft, LEGAL_GROUNDING_PREFIX + reason)
    if rejected or not accepted:
        draft.status = VerificationStatus.NEEDS_VERIFICATION


@lru_cache(maxsize=1)
def _court_registry() -> list[dict[str, str]]:
    try:
        raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in raw.get("entries", []) if isinstance(item, dict)]


def _verified_court(research: LegalResearch) -> str:
    for note in research.notes:
        value = str(note or "").strip()
        if value.startswith("VERIFIED_COURT:"):
            return value.split(":", 1)[1].strip()
    return ""


def _city_from_party(values: list[str]) -> str:
    text = _party_text(values).lower().replace("ё", "е")
    cities = list(dict.fromkeys(str(item.get("city", "")).strip() for item in _court_registry()))
    for city in cities:
        if city and city.lower().replace("ё", "е") in text:
            return city
    return ""


def _economic_registry_court(city: str) -> str:
    for item in _court_registry():
        if (
            str(item.get("city", "")).lower() == (city or "").lower()
            and str(item.get("jurisdiction", "")).lower() == "economic"
        ):
            return str(item.get("court", "")).strip()
    return ""


def _gpk27_supports_business_court() -> bool:
    if not local_corpus_enabled():
        return False
    corpus = open_corpus()
    if corpus is None:
        return False
    try:
        article_rows = _rows(corpus, ACT_GPK, "27")
    finally:
        corpus.close()
    text = " ".join(_actual_text(row) for row in article_rows).lower().replace("ё", "е")
    return "экономическ" in text and "юридическ" in text and "предпринимател" in text


def _apply_court_gate(research: LegalResearch, draft: ClaimDraft) -> None:
    if not (_is_business_subject(draft.claimant) and _is_business_subject(draft.defendant)):
        return

    verified = _verified_court(research)
    if verified and _ECONOMIC_COURT_RE.search(verified):
        draft.court = verified
        return
    if verified and _SPECIAL_JURISDICTION_RE.search(verified):
        return

    if not _gpk27_supports_business_court():
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        _add_note(
            draft,
            FILING_ACTION_PREFIX
            + "подтвердить компетенцию суда для спора между субъектами предпринимательства по актуальной редакции ГПК РК.",
        )
        if "экономическ" not in (draft.court or "").lower():
            draft.court = "[ТРЕБУЕТ УТОЧНЕНИЯ: специализированный межрайонный экономический суд по территориальной подсудности]"
        return

    court = _economic_registry_court(_city_from_party(draft.defendant))
    if court:
        draft.court = court
        note = f"VERIFIED_COURT: {court}"
        if note not in research.notes:
            research.notes.append(note)
        draft.verification_notes = [
            item
            for item in draft.verification_notes
            if not (str(item).startswith(FILING_ACTION_PREFIX) and "суд" in str(item).lower())
        ]
        return

    draft.status = VerificationStatus.NEEDS_VERIFICATION
    draft.court = "[ТРЕБУЕТ УТОЧНЕНИЯ: специализированный межрайонный экономический суд по территориальной подсудности]"
    _add_note(
        draft,
        FILING_ACTION_PREFIX + "подтвердить точное официальное наименование экономического суда по месту надлежащей подсудности.",
    )


def _positive_state_duty(draft: ClaimDraft) -> bool:
    text = draft.state_duty or ""
    if "льгот" in text.lower() or "освобожд" in text.lower() or "[" in text:
        return False
    for match in _POSITIVE_MONEY_RE.finditer(text):
        digits = re.sub(r"[\s\u00a0]", "", match.group(1)).replace(",", ".")
        try:
            if float(digits) > 0:
                return True
        except ValueError:
            continue
    return False


def _apply_filing_prerequisites(case_context: str, draft: ClaimDraft) -> None:
    claimant_text = " ".join([_party_text(draft.claimant), _claimant_context(case_context)])
    if _is_legal_entity(draft.claimant) and not _BANK_RE.search(claimant_text):
        _add_note(
            draft,
            FILING_ACTION_PREFIX + "указать банковские реквизиты истца-юридического лица перед подачей иска.",
        )

    attachments = "\n".join(str(item or "") for item in draft.attachments)
    if _positive_state_duty(draft) and not _DUTY_PROOF_RE.search(attachments):
        _add_note(
            draft,
            FILING_ACTION_PREFIX
            + "приложить документ об уплате государственной пошлины либо документ/ходатайство, подтверждающее законное основание не прикладывать оплату.",
        )
    if _is_legal_entity(draft.claimant) and not _REGISTRATION_RE.search(attachments):
        _add_note(
            draft,
            FILING_ACTION_PREFIX
            + "приложить документ о государственной регистрации/перерегистрации истца-юридического лица, если он требуется для подачи.",
        )


def apply_claim_filing_accuracy(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> None:
    """Apply zero-call, fail-closed filing accuracy rules to every claim draft."""
    _ground_legal_basis(research, draft)
    _apply_court_gate(research, draft)
    _apply_filing_prerequisites(case_context, draft)
    draft.verification_notes = list(dict.fromkeys(str(item) for item in draft.verification_notes if str(item).strip()))
