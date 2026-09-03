from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any

from fastapi import HTTPException

from korgan import citation_audit
from korgan import document_quality as quality
from korgan.legal_calc import parse_all_amounts_kzt
from korgan.legal_provenance import forbidden_fact_findings
from korgan.strict_openai import StrictOpenAILegalService

# The final document may cite a provision only when the same provision survived
# source-bound research for THIS request.  The local corpus remains useful as a
# validator/cache, but it cannot by itself promote a model citation to a final
# filing-ready document.
_TRUTH_PREFIX = "TRUTH_GUARD: "

# Current official Adilet document ids.  A model opening an Adilet page is not
# enough: for acts with a deterministic id below, the cited act must be bound to
# the correct current document.  This also prevents an obsolete/foreign act from
# being used under a correct-looking article number.
_CORE_ACT_SOURCE_IDS: dict[str, tuple[str, ...]] = {
    "ГПК РК": ("K1500000377",),
    "ГК РК": ("K940001000_", "K990000409_"),
    "НК РК": ("K2500000214",),
    "ТК РК": ("K1500000414",),
    "КАС РК": ("K2000000350",),
    "КоАП РК": ("K1400000235",),
    "ЗПП РК": ("Z100000274_",),
}

_PERCENT_OR_RATE_RE = re.compile(
    r"(?<!\d)(?:\d+(?:[.,]\d+)?)\s*(?:%|процент\w*|пайыз\w*)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?<!\d)(?:\d+(?:[.,]\d+)?)\s*(?:"
    r"(?:рабоч\w*|календарн\w*)\s+дн\w*|дн\w*|сут\w*|"
    r"недел\w*|месяц\w*|год\w*|лет\b|"
    r"(?:жұмыс|күнтізбелік)\s+күн\w*|күн\w*|апта\w*|ай\w*|жыл\w*"
    r")",
    re.IGNORECASE,
)
_MRP_RE = re.compile(r"(?<!\d)(?:\d+(?:[.,]\d+)?)\s*МРП\b", re.IGNORECASE)
_HIGH_RISK_FACT_PREFIXES = (
    "ФИО отсутствует",
    "ИИН/БИН отсутствует",
    "адрес отсутствует",
    "номер договора отсутствует",
    "дата отсутствует",
    "сумма отсутствует",
)

_INSTALLED = False
_ORIGINAL_COMMON_HYGIENE = quality._common_hygiene
_ORIGINAL_CURRENT_SOURCE = StrictOpenAILegalService._is_current_official_source

# citation_audit historically covered codes but not the consumer act by its
# common filing name.  Add that act to the same deterministic parser so a
# consumer-law citation cannot evade the live-source guard merely by naming the
# statute instead of a code abbreviation.
if not any(act == "ЗПП РК" for _, act in citation_audit._ACT_PATTERNS):
    citation_audit._ACT_PATTERNS = (
        *citation_audit._ACT_PATTERNS,
        (r"закон\w*\s+(?:рк\s+)?[«\"]?о\s+защит\w*\s+прав\w*\s+потребител\w*", "ЗПП РК"),
    )


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("ё", "е").lower())


def _is_russian_adilet(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in {"adilet.zan.kz", "www.adilet.zan.kz"}:
        return False
    return parsed.path.startswith("/rus/docs/")


def _current_source_strict(self: StrictOpenAILegalService, url: str) -> bool:
    """Keep the existing obsolete-act denylist and reject wrong Adilet locale.

    Court directories (gov.kz/sud.gov.kz) are left to the original policy; only
    legislation pages are constrained to the Russian official text used by the
    document/citation pipeline.
    """
    if not _ORIGINAL_CURRENT_SOURCE(self, url):
        return False
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host in {"adilet.zan.kz", "www.adilet.zan.kz"}:
        return parsed.path.startswith("/rus/docs/")
    return True


def _source_matches_reference(record: citation_audit.RuntimeProvision) -> bool:
    if not _is_russian_adilet(record.source_url):
        return False
    expected = _CORE_ACT_SOURCE_IDS.get(record.reference.act)
    if not expected:
        # For acts outside the deterministic core, source-bound live Adilet is
        # still required.  We do not guess an act id that the code does not own.
        return True
    return any(marker in record.source_url for marker in expected)


def live_citation_findings(
    text: str,
    verified_claims: list[str] | None,
) -> list[str]:
    """Every article named in client-facing text must come from live VERIFIED.

    citation_audit may use the local corpus as a fallback when reviewing a
    preliminary draft.  Filing-ready release is intentionally stricter: a
    concrete article number must also have a source-bound runtime provision from
    the current document research pass.
    """
    references = citation_audit.extract_references(text or "")
    if not references:
        return []

    runtime = [
        record
        for record in citation_audit.runtime_provisions(verified_claims)
        if _source_matches_reference(record)
    ]
    findings: list[str] = []
    for reference in references:
        if any(reference.matches(record.reference) for record in runtime):
            continue
        findings.append(
            f"{reference.label()} отсутствует в live source-bound VERIFIED текущего документа"
        )
    return list(dict.fromkeys(findings))


def _number_tokens(text: str) -> list[str]:
    values: list[str] = []
    for pattern in (_PERCENT_OR_RATE_RE, _DURATION_RE, _MRP_RE):
        values.extend(match.group(0).strip() for match in pattern.finditer(text or ""))
    return list(dict.fromkeys(values))


def _finding_supported_by_verified(finding: str, verified_text: str) -> bool:
    """Allow a high-risk value only if its literal value is in VERIFIED law.

    This is deliberately narrow.  It does not let a legal rule invent a party,
    address or commercial amount; it merely prevents a statutory date/number
    repeated verbatim from being mistaken for a model-created fact.
    """
    tail = str(finding or "").split(":", 1)[-1].strip()
    if not tail:
        return False
    # Literal compact matching is safer than concatenating every digit in the
    # whole VERIFIED block: the latter could accidentally manufacture a match
    # from an article number plus an unrelated date/amount.
    return _norm(tail) in _norm(verified_text)


def contract_truth_findings(
    lines: list[str],
    *,
    case_context: str,
    verified_claims: list[str] | None,
) -> list[str]:
    """Block model-created commercial numbers and party/document particulars.

    A contract is allowed to *structure* missing terms with placeholders.  It is
    not allowed to fill them with plausible values.  Percentages and durations
    may come from the user or a VERIFIED mandatory rule; monetary amounts come
    from the user's materials (or an explicitly VERIFIED statutory threshold).
    """
    text = "\n".join(str(line or "") for line in lines if str(line or "").strip())
    verified_text = "\n".join(str(x) for x in (verified_claims or []))
    allowed_text = f"{case_context}\n{verified_text}"
    allowed_norm = _norm(allowed_text)
    findings: list[str] = []

    for token in _number_tokens(text):
        if _norm(token) not in allowed_norm:
            findings.append(f"числовое условие договора не подтверждено материалами/VERIFIED: {token}")

    allowed_amounts = set(parse_all_amounts_kzt(case_context)) | set(parse_all_amounts_kzt(verified_text))
    for amount in parse_all_amounts_kzt(text):
        if amount not in allowed_amounts:
            findings.append(
                "денежное условие договора не подтверждено материалами/VERIFIED: "
                + f"{amount:,} тенге".replace(",", " ")
            )

    # Reuse the mature provenance parser for the highest-risk factual entities,
    # but ignore evidence-event findings because a contract may legitimately
    # prescribe a future act/invoice without asserting that it already exists.
    for finding in forbidden_fact_findings(lines, case_context):
        if not finding.startswith(_HIGH_RISK_FACT_PREFIXES):
            continue
        if _finding_supported_by_verified(finding, verified_text):
            continue
        findings.append(finding)

    return list(dict.fromkeys(findings))


def _truth_common_hygiene(
    kind: quality.DocumentKind,
    lines: list[str],
    blockers: list[str],
    issues: list[str],
    *,
    case_context: str = "",
    verified_claims: list[str] | None = None,
    verification_notes: list[str] | None = None,
) -> float:
    score = _ORIGINAL_COMMON_HYGIENE(
        kind,
        lines,
        blockers,
        issues,
        case_context=case_context,
        verified_claims=verified_claims,
        verification_notes=verification_notes,
    )

    text = "\n".join(str(line or "") for line in lines if str(line or "").strip())
    truth_findings = live_citation_findings(text, verified_claims)
    if kind == "contract":
        truth_findings.extend(
            contract_truth_findings(
                lines,
                case_context=case_context,
                verified_claims=verified_claims,
            )
        )

    for finding in list(dict.fromkeys(truth_findings)):
        marker = _TRUTH_PREFIX + finding
        if marker not in blockers:
            blockers.append(marker)
        score -= 0.6
    return max(0.0, score)


def _truth_blockers(meta: dict[str, Any]) -> list[str]:
    return [
        str(issue)
        for issue in list(meta.get("quality_issues") or [])
        if str(issue).startswith(_TRUTH_PREFIX)
    ]


def install_document_truth_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    StrictOpenAILegalService._is_current_official_source = _current_source_strict
    quality._common_hygiene = _truth_common_hygiene

    # Patch the Mini App's final release function rather than route ownership.
    # UniversalQualityProductionService has already had one bounded repair chance
    # by this stage.  If a fabricated fact/term or non-live citation survives,
    # returning a PRELIMINARY Word file would still expose false legal content.
    from korgan import miniapp_api_v2 as core

    if not getattr(core, "_korgan_truth_release_installed", False):
        original_release = core._release_metadata

        def truth_release_metadata(document_type: str, context: str, research: Any, draft: Any) -> dict[str, Any]:
            meta = original_release(document_type, context, research, draft)
            blockers = _truth_blockers(meta)
            if blockers:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "KORGAN не выпустил документ: финальная проверка обнаружила "
                        "неподтвержденную статью либо выдуманный реквизит/условие. "
                        + blockers[0].removeprefix(_TRUTH_PREFIX)
                    ),
                )
            return meta

        core._release_metadata = truth_release_metadata
        core._korgan_truth_release_installed = True

    _INSTALLED = True


install_document_truth_runtime()
