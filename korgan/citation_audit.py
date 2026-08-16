"""Post-processing audit of every legal citation in a finished document.

Verification that happens "along the way", inside a long generation with several
citations, is verification that happens sometimes. In the reported documents the
same model quoted статьи 953 и 960 ГК РК perfectly and часть 2 статьи 166 ГПК РК
from a repealed edition — in one document. The step did not fail as a rule; it
failed per citation.

So it is not a step of drafting any more. Once a draft exists, this module walks
the finished text, finds every reference to a provision, and re-checks each one
on its own against korgan.provision_corpus:

* a verbatim quotation must match the corpus text symmetrically — normalized for
  spacing, ё and quote glyphs, and nothing else. Partial overlap is not a pass;
* a paraphrase is screened by korgan.provision_check against the corpus text;
* a provision absent from the corpus may not be quoted or asserted at all — the
  document may name the article number and must mark it NEEDS_VERIFICATION;
* a corpus record that was never read from the official source (REPORTED) may be
  used only with a visible verification marker in the document.

The audit is document-type agnostic: it reads text, so it applies to all eight
document types rather than to the one where the defect was noticed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from korgan.provision_check import paraphrase_defects
from korgan.provision_corpus import (
    ProvisionRecord,
    lookup,
    normalize_text,
)

# «часть 4 статьи 166 ГПК РК», «ст. 953 ГК РК», «пункт 1 статьи 960 ГК РК»
_REFERENCE_RE = re.compile(
    # Any case form of часть/пункт/подпункт, then the article number.
    r"(?:(?:част[ьияею]\w*|ч\.|подпункт\w*|пп\.|пункт\w*|п\.)\s*(?P<part>\d+)\s*)?"
    r"(?:стать[ияеёю]\w*|ст\.)\s*(?P<article>\d+)"
    r"(?P<tail>[^.;)\n]{0,60})",
    re.IGNORECASE,
)

# «... текст ...» — a verbatim quotation.
_QUOTE_RE = re.compile(r"[«\"]([^«»\"]{25,})[»\"]")

_ACT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс", "ГПК РК"),
    (r"гк\s*рк|гражданск\w*\s+кодекс", "ГК РК"),
    (r"нк\s*рк|налогов\w*\s+кодекс", "НК РК"),
    (r"тк\s*рк|трудов\w*\s+кодекс", "ТК РК"),
    (r"кас\s*рк|административн\w*\s+процедурн", "КАС РК"),
    (r"коап\s*рк|об\s+административных\s+правонарушениях", "КоАП РК"),
)

# The visible marker a document must carry when it relies on unverified wording.
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
        return [finding.as_note() for finding in self.findings if finding.verdict is not CitationVerdict.QUOTE_MATCHES]


def _detect_act(window: str) -> str:
    lowered = normalize_text(window)
    for pattern, act in _ACT_PATTERNS:
        if re.search(pattern, lowered):
            return act
    return ""


def _paragraph_around(text: str, position: int) -> str:
    """The paragraph a reference sits in.

    Paragraph, not sentence: a quotation contains full stops of its own, and a
    `[ТРЕБУЕТ ПРОВЕРКИ: ...]` marker spans several sentences. Scoping to the
    paragraph also stops a reference from borrowing the quotation that belongs
    to a different provision further down the document.
    """
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return text[start : end if end != -1 else len(text)]


def _marked_for_verification(context: str) -> bool:
    upper = context.upper()
    return any(marker in upper for marker in VERIFICATION_MARKERS)


def _quote_in(paragraph: str) -> str:
    """Return the verbatim quotation carried by this paragraph, if any."""
    matches = _QUOTE_RE.findall(paragraph)
    return max(matches, key=len) if matches else ""


@dataclass(frozen=True, slots=True)
class ProvisionReference:
    """A provision named in free text — act, article and optional part."""

    act: str
    article: str
    part: str = ""

    def label(self) -> str:
        return f"{'часть ' + self.part + ' ' if self.part else ''}статья {self.article} {self.act}".strip()

    def genitive(self) -> str:
        """«статьи 616 ГК РК» — форма для встраивания в текст документа.

        `label` — ярлык для служебных сообщений; подставленный в предложение он
        даёт «содержание статья 616 ГК РК», что в судебном документе читается
        как брак вёрстки.
        """
        return f"{'части ' + self.part + ' ' if self.part else ''}статьи {self.article} {self.act}".strip()

    def matches(self, other: "ProvisionReference") -> bool:
        """Same act and article; a reference without a part matches any part."""
        if self.act != other.act or self.article != other.article:
            return False
        return not self.part or not other.part or self.part == other.part


def extract_references(text: str) -> list[ProvisionReference]:
    """Every provision named in ``text``, in order of appearance.

    Shared with the instruction router: when a user writes «пометь статью 616
    ГК РК», the article they mean is found exactly the way the audit finds the
    articles it complained about.
    """
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


def _record_detail(record: ProvisionRecord) -> str:
    when = record.verified_on or "дата сверки не зафиксирована"
    return f"источник: {record.source_url or 'не указан'}; сверено: {when}"


def audit_citations(text: str) -> CitationAudit:
    """Re-check every provision reference in a finished document, one by one."""
    audit = CitationAudit()
    seen: set[tuple[str, str, str, bool]] = set()

    for match in _REFERENCE_RE.finditer(text or ""):
        article = match.group("article")
        part = (match.group("part") or "").strip()
        act = _detect_act(match.group(0) + " " + (match.group("tail") or ""))
        if not act:
            act = _detect_act(_paragraph_around(text, match.start()))
        if not act:
            # Без указания акта это не ссылка на норму (например, «пункт 3 договора»).
            continue

        context = _paragraph_around(text, match.start())
        quote = _quote_in(context)
        signature = (act, article, part, bool(quote))
        if signature in seen:
            continue
        seen.add(signature)

        reference = f"{'часть ' + part + ' ' if part else ''}статья {article} {act}"
        record = lookup(act, article, part)

        if record is None:
            verdict = CitationVerdict.UNVERIFIABLE
            detail = (
                "текста нормы нет в проверенном корпусе KORGAN — содержание не подтверждено; "
                "допустимо указать только номер статьи и пометить NEEDS_VERIFICATION"
            )
            if not quote and _marked_for_verification(context):
                verdict = CitationVerdict.UNVERIFIED_SOURCE
                detail = (
                    "текста нормы нет в корпусе; в документе содержание не утверждается и стоит "
                    "пометка о необходимости сверки"
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
