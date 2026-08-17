"""Final legal-release hardening shared by claims and pre-trial demands."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from korgan.citation_audit import extract_references
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.legal.rk_catalog import CITATION_ACT_IDS
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.request_basis_coverage import ensure_request_basis_coverage

_LANGUAGE_LABEL_RE = re.compile(
    r"(?i)"
    r"\s*\((?:русск\w*\s+редакц\w*|англ\w*\s+(?:верси\w*|редакц\w*)|english\s+version|russian\s+version)\)"
    r"|\b(?:русск\w*\s+редакц\w*|англ\.?\s*(?:верси\w*|редакц\w*)|английск\w*\s+(?:верси\w*|редакц\w*))\b"
)
_SYSTEM_LINK_RE = re.compile(r"(?i),?\s*в\s+системн\w*\s+связ\w*\s+с\s+(?=(?:англ\.?|английск\w*|русск\w*))")
_SOURCE_RE = re.compile(r"источник:\s*(https?://[^\]\s]+)", re.IGNORECASE)
_VERIFIED_RE = re.compile(r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:", re.IGNORECASE | re.DOTALL)

_SALARY_RE = re.compile(r"(?i)заработн\w*\s+плат|зарплат\w*|еңбекақ\w*")
_LEAVE_COMP_RE = re.compile(r"(?i)(?:неиспользован\w*\s+отпуск|компенсац\w*.*отпуск|демалыс.*өтемақ|өтемақ.*демалыс)")
_IMMEDIATE_RE = re.compile(r"(?i)(?:немедленн\w*\s+исполн|дереу\s+орында)")


def clean_language_labels(text: str) -> str:
    value = _SYSTEM_LINK_RE.sub(", ", str(text or ""))
    value = _LANGUAGE_LABEL_RE.sub("", value)
    value = re.sub(r"(?i)\bангл\.?\s+(?=ст\.|стать)", "", value)
    value = re.sub(r"(?i)\bрусск\.?\s+(?=ст\.|стать)", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = re.sub(r"\s+,", ",", value)
    return value.strip()


def _is_russian_adilet(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in {"adilet.zan.kz", "www.adilet.zan.kz"}:
        return True
    return parsed.path.startswith("/rus/")


def _reference_key(text: str) -> tuple[tuple[str, str, str], ...]:
    return tuple((ref.act, ref.article, ref.part) for ref in extract_references(text))


def _dedupe_by_article(lines: list[str]) -> list[str]:
    cleaned = [clean_language_labels(line) for line in lines if clean_language_labels(line)]
    slots: list[tuple[tuple[tuple[str, str, str], ...], str]] = []
    positions: dict[tuple[tuple[str, str, str], ...], int] = {}
    seen_plain: set[str] = set()
    for line in cleaned:
        key = _reference_key(line)
        if key:
            if key in positions:
                idx = positions[key]
                if len(line) > len(slots[idx][1]):
                    slots[idx] = (key, line)
                continue
            positions[key] = len(slots)
            slots.append((key, line))
            continue
        plain = re.sub(r"\W+", "", line.lower())
        if plain and plain not in seen_plain:
            seen_plain.add(plain)
            slots.append(((), line))
    return [line for _, line in slots]


def sanitize_research_sources(research: LegalResearch) -> LegalResearch:
    """Reject non-Russian Adilet pages and language-version framing before drafting."""
    accepted: list[str] = []
    rejected = list(research.unverified_claims)
    for line in research.verified_claims:
        match = _SOURCE_RE.search(str(line))
        source = match.group(1).rstrip(".,;)") if match else ""
        if source and not _is_russian_adilet(source):
            rejected.append("Правовой вывод не использован: открыта не русская официальная страница Adilet.")
            continue
        accepted.append(clean_language_labels(str(line)))
    accepted = _dedupe_by_article(accepted)
    sources = [url for url in research.source_urls if _is_russian_adilet(url)]
    research.verified_claims = accepted
    research.source_urls = list(dict.fromkeys(sources))
    research.unverified_claims = list(dict.fromkeys(x for x in rejected if x))
    if not accepted:
        research.status = VerificationStatus.NEEDS_VERIFICATION
    return research


def _has_article(lines: list[str], act: str, articles: set[str]) -> bool:
    for line in lines:
        for ref in extract_references(line):
            if ref.act == act and ref.article in articles:
                return True
    return False


def _render_verified(research: LegalResearch, act: str, articles: set[str]) -> list[str]:
    rendered: list[str] = []
    for line in research.verified_claims:
        refs = extract_references(line)
        if not any(ref.act == act and ref.article in articles for ref in refs):
            continue
        match = _VERIFIED_RE.search(line)
        if not match:
            continue
        statement = clean_language_labels(" ".join(match.group("statement").split()).strip(" ."))
        article = clean_language_labels(" ".join(match.group("article").split()).strip(" ."))
        if statement and article:
            rendered.append(f"{statement}. Правовое основание: {article}.")
    return _dedupe_by_article(rendered)


def normalize_claim_legal_basis(draft: ClaimDraft, research: LegalResearch) -> list[str]:
    """Normalize citations and keep hard article checks for employment remedies."""
    draft.legal_basis = _dedupe_by_article(list(draft.legal_basis))
    requests = "\n".join(str(x) for x in draft.requests)
    requirements: list[tuple[re.Pattern[str], str, set[str], str]] = [
        (_SALARY_RE, "ТК РК", {"23", "113"}, "взыскание заработной платы"),
        (_LEAVE_COMP_RE, "ТК РК", {"96"}, "компенсация за неиспользованный отпуск"),
        (_IMMEDIATE_RE, "ГПК РК", {"243"}, "немедленное исполнение решения о заработной плате"),
    ]
    missing: list[str] = []
    for pattern, act, articles, label in requirements:
        if not pattern.search(requests):
            continue
        if not _has_article(draft.legal_basis, act, articles):
            additions = _render_verified(research, act, articles)
            if additions:
                draft.legal_basis.extend(additions)
                draft.legal_basis = _dedupe_by_article(draft.legal_basis)
            if not _has_article(draft.legal_basis, act, articles):
                missing.append(label)
    if missing:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = "Нет отдельной VERIFIED правовой опоры для требований: " + "; ".join(missing)
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
    return missing


class StableLegalProductionService(FinalizedProductionClaimService):
    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        research = await super().research_case(case_context, language=language)
        return sanitize_research_sources(research)

    async def draft_claim(self, case_context: str, research: LegalResearch, language: str = "ru") -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        normalize_claim_legal_basis(draft, research)
        ensure_request_basis_coverage(case_context, draft, research)
        draft.legal_basis = _dedupe_by_article(draft.legal_basis)
        return draft


def install_stable_legal_release() -> None:
    """Install production research rules and local-corpus citation aliases."""
    from korgan import client_safe_ui
    from korgan import fast_professional_litigation as litigation

    client_safe_ui._ACT_IDS.update(CITATION_ACT_IDS)

    if getattr(litigation, "_stable_legal_release_prompt_installed", False):
        return
    original = litigation._professional_research_prompt

    def stable_prompt(case_context: str, *, max_chars: int, checked_on: str, **kwargs: object) -> str:
        base = original(case_context, max_chars=max_chars, checked_on=checked_on, **kwargs)
        return base + (
            "\n\nСТАБИЛЬНОСТЬ ИСТОЧНИКОВ И ПОКРЫТИЕ ТРЕБОВАНИЙ:\n"
            "21. Для норм права открывай только русскую официальную страницу Adilet вида /rus/docs/. "
            "Не используй /eng/docs/ как отдельный источник и никогда не пиши 'английская версия' или 'русская редакция': это один нормативный акт.\n"
            "22. Для КАЖДОГО самостоятельного требования в просительной части найди отдельную VERIFIED норму, которая поддерживает именно это юридическое последствие. "
            "Нельзя обосновать только часть иска и оставить другое требование без правовой опоры.\n"
            "23. В трудовом споре отдельно проверь: задолженность по заработной плате — ст. 113 ТК РК (и иные прямо применимые нормы); "
            "компенсацию за неиспользованный отпуск — ст. 96 ТК РК; при требовании немедленного исполнения заработной платы — ст. 243 ГПК РК. "
            "Принимай статьи только после source-bound проверки действующей русской страницы Adilet.\n"
            "24. Не создавай несколько verified_points с одним и тем же актом и номером статьи ради языковых страниц или почти одинаковых пересказов. "
            "Одна норма — один точный verified_point, если разные пункты не дают действительно разные правила.\n"
            "25. Если отдельное требование не удалось связать с точной VERIFIED нормой, не маскируй пробел общими принципами: пометь его как непокрытое для внутреннего quality-gate."
        )

    litigation._professional_research_prompt = stable_prompt
    litigation._stable_legal_release_prompt_installed = True
