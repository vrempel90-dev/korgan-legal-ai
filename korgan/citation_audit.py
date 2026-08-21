"""Post-processing audit of every legal citation in a finished document.

The release audit has two verified sources, in this order:

1. source-bound provisions verified for the current document by the live legal
   research pass (official Adilet URL + provision text + paraphrase check);
2. the dated local provision corpus as a reusable fallback/cache.

A model cannot promote its own citation into the first source: runtime records
are built only from ``LegalResearch.verified_claims`` after the research layer
has already matched an actually opened official URL and checked the statement
against the provision's own words.

Anything absent from both sources may not be asserted confidently. The document
may name the article number only with an explicit verification marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from korgan.provision_check import paraphrase_defects, quote_is_usable
from korgan.provision_corpus import ProvisionRecord, lookup, normalize_text

# «часть 4 статьи 166 ГПК РК», «ст. 953 ГК РК», «пункт 1 статьи 960 ГК РК»
_REFERENCE_RE = re.compile(
    r"(?:(?:част[ьияею]\w*|ч\.|подпункт\w*|пп\.|пункт\w*|п\.)\s*(?P<part>\d+)\s*)?"
    r"(?:стать[ияеёю]\w*|ст\.)\s*(?P<article>\d+(?:-\d+)?)"
    r"(?P<tail>[^.;)\n]{0,60})",
    re.IGNORECASE,
)

# «... текст ...» — a verbatim quotation.
_QUOTE_RE = re.compile(r"[«\"]([^«»\"]{25,})[»\"]")

# verified_claim_line() format from korgan.provision_check.
_RUNTIME_TEXT_RE = re.compile(
    r"текст\s+нормы\s*:\s*«(?P<text>.*?)»\s*;\s*источник\s*:\s*(?P<url>https?://[^\]\s]+)",
    re.IGNORECASE | re.DOTALL,
)

_ACT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс", "ГПК РК"),
    (r"гк\s*рк|гражданск\w*\s+кодекс", "ГК РК"),
    (r"нк\s*рк|налогов\w*\s+кодекс", "НК РК"),
    (r"тк\s*рк|трудов\w*\s+кодекс", "ТК РК"),
    (r"кас\s*рк|административн\w*\s+процедурн", "КАС РК"),
    (r"коап\s*рк|об\s+административных\s+правонарушениях", "КоАП РК"),
)

VERIFICATION_MARKERS = ("[ТРЕБУЕТ ПРОВЕРКИ", "[ТРЕБУЕТ УТОЧНЕНИЯ", "NEEDS_VERIFICATION")


class CitationVerdict(StrEnum):
    QUOTE_MATCHES = "QUOTE_MATCHES"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    PARAPHRASE_OK = "PARAPHRASE_OK"
    PARAPHRASE_DRIFT = "PARAPHRASE_DRIFT"
    UNVERIFIABLE = "UNVERIFIABLE"
    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"


_BLOCKING = {
    CitationVerdict.QUOTE_MISMATCH,
    CitationVerdict.PARAPHRASE_DRIFT,
    CitationVerdict.UNVERIFIABLE,
}


@dataclass(slots=True)
class CitationFinding:
    reference: str
    act: str
    article: str
    part: str
    verdict: CitationVerdict
    detail: str
    quoted: bool = False

    @property
    def blocks_release(self) -> bool:
        return self.verdict in _BLOCKING

    def as_note(self) -> str:
        return f"{self.reference}: {self.detail}"


@dataclass(slots=True)
class CitationAudit:
    findings: list[CitationFinding] = field(default_factory=list)

    @property
    def has_citations(self) -> bool:
        return bool(self.findings)

    @property
    def blocking(self) -> list[CitationFinding]:
        return [finding for finding in self.findings if finding.blocks_release]

    def notes(self) -> list[str]:
        return [
            finding.as_note()
            for finding in self.findings
            if finding.verdict not in {CitationVerdict.QUOTE_MATCHES, CitationVerdict.PARAPHRASE_OK}
        ]


@dataclass(frozen=True, slots=True)
class ProvisionReference:
    """A provision named in free text — act, article and optional part."""

    act: str
    article: str
    part: str = ""

    def label(self) -> str:
        return f"{'часть ' + self.part + ' ' if self.part else ''}статья {self.article} {self.act}".strip()

    def genitive(self) -> str:
        return f"{'части ' + self.part + ' ' if self.part else ''}статьи {self.article} {self.act}".strip()

    def matches(self, other: "ProvisionReference") -> bool:
        if self.act != other.act or self.article != other.article:
            return False
        return not self.part or not other.part or self.part == other.part


@dataclass(frozen=True, slots=True)
class RuntimeProvision:
    reference: ProvisionReference
    text: str
    source_url: str


def _detect_act(window: str) -> str:
    lowered = normalize_text(window)
    for pattern, act in _ACT_PATTERNS:
        if re.search(pattern, lowered):
            return act
    return ""


def _paragraph_around(text: str, position: int) -> str:
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return text[start : end if end != -1 else len(text)]


def _marked_for_verification(context: str) -> bool:
    upper = context.upper()
    return any(marker in upper for marker in VERIFICATION_MARKERS)


def _quote_in(paragraph: str) -> str:
    matches = _QUOTE_RE.findall(paragraph)
    return max(matches, key=len) if matches else ""


def extract_references(text: str) -> list[ProvisionReference]:
    """Every provision named in ``text``, in order of appearance."""
    found: list[ProvisionReference] = []
    for match in _REFERENCE_RE.finditer(text or ""):
        act = _detect_act(match.group(0) + " " + (match.group("tail") or ""))
        if not act:
            act = _detect_act(_paragraph_around(text, match.start()))
        if not act:
            continue
        reference = ProvisionReference(act, match.group("article"), (match.group("part") or "").strip())
        if reference not in found:
            found.append(reference)
    return found


def _is_adilet(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "adilet.zan.kz" or host.endswith(".adilet.zan.kz")


def runtime_provisions(verified_claims: list[str] | None) -> list[RuntimeProvision]:
    """Build per-document provision records from source-bound VERIFIED research.

    Only the canonical verified_claim_line shape with an Adilet URL and a usable
    provision quote is accepted. Arbitrary model/user strings are ignored.
    """
    records: list[RuntimeProvision] = []
    for line in verified_claims or []:
        match = _RUNTIME_TEXT_RE.search(line or "")
        if not match:
            continue
        provision_text = " ".join(match.group("text").split())
        source_url = match.group("url").rstrip(".,;)")
        if not _is_adilet(source_url) or not quote_is_usable(provision_text):
            continue
        references = extract_references(line)
        if not references:
            continue
        for reference in references:
            item = RuntimeProvision(reference, provision_text, source_url)
            if item not in records:
                records.append(item)
    return records


def _runtime_lookup(
    records: list[RuntimeProvision],
    act: str,
    article: str,
    part: str,
) -> RuntimeProvision | None:
    exact = [
        record
        for record in records
        if record.reference.act == act
        and record.reference.article == article
        and record.reference.part == part
    ]
    if exact:
        return exact[0]

    article_level = [
        record
        for record in records
        if record.reference.act == act
        and record.reference.article == article
        and not record.reference.part
    ]
    if article_level:
        return article_level[0]

    if not part:
        same_article = [
            record
            for record in records
            if record.reference.act == act and record.reference.article == article
        ]
        if len(same_article) == 1:
            return same_article[0]
    return None


def _record_detail(record: ProvisionRecord) -> str:
    when = record.verified_on or "дата сверки не зафиксирована"
    return f"источник: {record.source_url or 'не указан'}; сверено: {when}"


def _audit_against_runtime(
    *,
    reference_label: str,
    act: str,
    article: str,
    part: str,
    context: str,
    quote: str,
    runtime: RuntimeProvision,
) -> CitationFinding:
    if quote:
        if normalize_text(quote) == normalize_text(runtime.text):
            return CitationFinding(
                reference_label,
                act,
                article,
                part,
                CitationVerdict.QUOTE_MATCHES,
                f"дословная цитата совпадает с source-bound текстом нормы ({runtime.source_url})",
                quoted=True,
            )
        return CitationFinding(
            reference_label,
            act,
            article,
            part,
            CitationVerdict.QUOTE_MISMATCH,
            "дословная цитата не совпадает с текстом нормы, проверенным для текущего документа",
            quoted=True,
        )

    drift = paraphrase_defects(context, runtime.text)
    if drift:
        return CitationFinding(
            reference_label,
            act,
            article,
            part,
            CitationVerdict.PARAPHRASE_DRIFT,
            "; ".join(drift[:3]),
        )
    return CitationFinding(
        reference_label,
        act,
        article,
        part,
        CitationVerdict.PARAPHRASE_OK,
        f"пересказ сверен с source-bound текстом нормы ({runtime.source_url})",
    )


def audit_citations(
    text: str,
    *,
    verified_claims: list[str] | None = None,
) -> CitationAudit:
    """Re-check every provision reference in a finished document, one by one."""
    audit = CitationAudit()
    seen: set[tuple[str, str, str, bool, int]] = set()
    runtime_records = runtime_provisions(verified_claims)

    for match in _REFERENCE_RE.finditer(text or ""):
        article = match.group("article")
        part = (match.group("part") or "").strip()
        act = _detect_act(match.group(0) + " " + (match.group("tail") or ""))
        if not act:
            act = _detect_act(_paragraph_around(text, match.start()))
        if not act:
            continue

        context = _paragraph_around(text, match.start())
        quote = _quote_in(context)
        paragraph_start = text.rfind("\n", 0, match.start()) + 1
        signature = (act, article, part, bool(quote), paragraph_start)
        if signature in seen:
            continue
        seen.add(signature)

        reference = f"{'часть ' + part + ' ' if part else ''}статья {article} {act}"

        # Live source-bound verification is more current than the static cache
        # and is scoped to this exact document.
        runtime = _runtime_lookup(runtime_records, act, article, part)
        if runtime is not None:
            audit.findings.append(
                _audit_against_runtime(
                    reference_label=reference,
                    act=act,
                    article=article,
                    part=part,
                    context=context,
                    quote=quote,
                    runtime=runtime,
                )
            )
            continue

        record = lookup(act, article, part)
        if record is None:
            verdict = CitationVerdict.UNVERIFIABLE
            detail = (
                "текста нормы нет ни в source-bound VERIFIED текущего документа, ни в проверенном корпусе KORGAN; "
                "допустимо указать только номер статьи и пометить NEEDS_VERIFICATION"
            )
            if not quote and _marked_for_verification(context):
                verdict = CitationVerdict.UNVERIFIED_SOURCE
                detail = (
                    "содержание нормы не утверждается и явно помечено для дополнительной сверки"
                )
            audit.findings.append(
                CitationFinding(reference, act, article, part, verdict, detail, quoted=bool(quote))
            )
            continue

        if quote:
            if normalize_text(quote) == normalize_text(record.text):
                verdict = CitationVerdict.QUOTE_MATCHES
                detail = f"дословная цитата совпадает с корпусом ({_record_detail(record)})"
                if not record.citable_verbatim:
                    verdict = CitationVerdict.UNVERIFIED_SOURCE
                    detail = (
                        "цитата совпадает с записью корпуса, но запись не сверялась с официальным "
                        f"источником ({_record_detail(record)}); требуется сверка до подачи"
                    )
                    if not _marked_for_verification(context):
                        verdict = CitationVerdict.QUOTE_MISMATCH
                        detail = (
                            "дословная цитата выпущена без видимой пометки о необходимости сверки, "
                            "хотя запись корпуса официально не подтверждена"
                        )
            else:
                verdict = CitationVerdict.QUOTE_MISMATCH
                detail = (
                    "дословная цитата не совпадает с текстом нормы посимвольно — частичное совпадение "
                    f"не принимается ({_record_detail(record)})"
                )
            audit.findings.append(
                CitationFinding(reference, act, article, part, verdict, detail, quoted=True)
            )
            continue

        drift = paraphrase_defects(context, record.text)
        if drift:
            audit.findings.append(
                CitationFinding(
                    reference,
                    act,
                    article,
                    part,
                    CitationVerdict.PARAPHRASE_DRIFT,
                    "; ".join(drift[:3]),
                )
            )
            continue

        verdict = CitationVerdict.PARAPHRASE_OK
        detail = f"пересказ сверен с текстом нормы ({_record_detail(record)})"
        if not record.citable_verbatim:
            verdict = CitationVerdict.UNVERIFIED_SOURCE
            detail = (
                "пересказ сверен с записью корпуса, но запись не подтверждена официальным источником "
                f"({_record_detail(record)})"
            )
        audit.findings.append(CitationFinding(reference, act, article, part, verdict, detail))

    return audit
