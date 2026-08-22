"""Kazakh-language compatibility for the proven Russian-first legal quality core.

The source corpus remains the official Russian Adilet edition used for exact
verification.  Client-facing legal prose may be Kazakh, but article identity,
source binding, fact lock and the >=8.5 quality gate remain the same.
"""

from __future__ import annotations

import re
from typing import Any

from korgan.i18n import KK
from korgan.language_context import current_language


_ARTICLE_BILINGUAL = re.compile(
    r"(?i)(?:(?:стать[ьяиеёю]\w*|ст\.)\s*\d+(?:-\d+)?|\b\d+(?:-\d+)?\s*[-–]?\s*бап(?:ы|тың|тің|та|те|қа|ке|пен|бында|бінде|тан|тен)?\b)"
)
_KK_REFERENCE_RE = re.compile(
    r"(?P<article>\d+(?:-\d+)?)\s*[-–]?\s*бап(?:ы|тың|тің|та|те|қа|ке|пен|бында|бінде|тан|тен)?"
    r"(?:\s*(?:ның|нің)?\s*(?P<part>\d+)\s*[-–]?\s*(?:тармағ\w*|бөліг\w*))?",
    re.IGNORECASE,
)

_KK_ACT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bқр\s*апк\b|азаматтық\s+процестік\s+кодекс", "ГПК РК"),
    (r"\bқр\s*ак\b|азаматтық\s+кодекс", "ГК РК"),
    (r"\bқр\s*ск\b|салық\s+кодекс", "НК РК"),
    (r"\bқр\s*ек\b|еңбек\s+кодекс", "ТК РК"),
    (r"\bқр\s*әрпк\b|әкімшілік\s+рәсімдік.{0,20}процестік\s+кодекс", "КАС РК"),
    (r"әкімшілік\s+құқық\s+бұзушылық.*кодекс", "КоАП РК"),
)


def _kk_act(text: str) -> str:
    lowered = (text or "").lower()
    for pattern, act in _KK_ACT_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return act
    return ""


def _article_to_kk(value: str) -> str:
    text = " ".join(str(value or "").split())
    patterns = (
        (r"(?i)(?:стать[ьяи]\w*|ст\.)\s*(\d+(?:-\d+)?)\s*(?:гк\s*рк|гражданск\w*\s+кодекс\w*\s+рк)", r"ҚР АК \1-бабы"),
        (r"(?i)(?:стать[ьяи]\w*|ст\.)\s*(\d+(?:-\d+)?)\s*(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс\w*)", r"ҚР АПК \1-бабы"),
        (r"(?i)(?:стать[ьяи]\w*|ст\.)\s*(\d+(?:-\d+)?)\s*(?:нк\s*рк|налогов\w*\s+кодекс\w*)", r"ҚР СК \1-бабы"),
        (r"(?i)(?:стать[ьяи]\w*|ст\.)\s*(\d+(?:-\d+)?)\s*(?:тк\s*рк|трудов\w*\s+кодекс\w*)", r"ҚР ЕК \1-бабы"),
    )
    for pattern, replacement in patterns:
        replaced = re.sub(pattern, replacement, text)
        if replaced != text:
            return replaced
    return text


def install_kazakh_legal_bridge() -> None:
    from korgan import bot as base_bot
    from korgan import citation_audit
    from korgan import claim_quality_hotfix as hotfix
    from korgan import document_quality
    from korgan import legal_basis_fit
    from korgan import professional_claim_finalizer as finalizer
    from korgan import senior_claim_preflight as senior

    if getattr(citation_audit, "_korgan_kazakh_bridge_installed", False):
        return

    original_extract = citation_audit.extract_references

    def extract_references_bilingual(text: str) -> list[citation_audit.ProvisionReference]:
        found = list(original_extract(text))
        source = text or ""
        for match in _KK_REFERENCE_RE.finditer(source):
            start = source.rfind("\n", 0, match.start()) + 1
            end = source.find("\n", match.end())
            paragraph = source[start : end if end >= 0 else len(source)]
            act = _kk_act(paragraph)
            if not act:
                window = source[max(0, match.start() - 100) : min(len(source), match.end() + 100)]
                act = _kk_act(window)
            if not act:
                continue
            ref = citation_audit.ProvisionReference(
                act=act,
                article=match.group("article"),
                part=(match.group("part") or "").strip(),
            )
            if ref not in found:
                found.append(ref)
        return found

    citation_audit.extract_references = extract_references_bilingual
    base_bot.extract_references = extract_references_bilingual

    # universal_claim_runtime was imported by install_runtime_hotfix before this
    # bridge is installed, so refresh its direct binding as well.
    try:
        from korgan import universal_claim_runtime
        universal_claim_runtime.extract_references = extract_references_bilingual
    except Exception:
        pass

    # Article detection used by quality scoring / verified-article transfer.
    document_quality._ARTICLE_RE = _ARTICLE_BILINGUAL
    hotfix._ARTICLE_TOKEN_RE = _ARTICLE_BILINGUAL
    finalizer._ARTICLE_RE = _ARTICLE_BILINGUAL

    # Kazakh placeholders and party forms must be evaluated exactly like Russian.
    document_quality._PLACEHOLDER_RE = re.compile(
        r"\[(?:ТРЕБУЕТ УТОЧНЕНИЯ|ТРЕБУЕТ ПРОВЕРКИ|ТРЕБУЕТ РАСЧ[ЕЁ]ТА|ТРЕБУЕТ ДОБАВИТЬ|НАҚТЫЛАУ ҚАЖЕТ|ТЕКСЕРУ ҚАЖЕТ|ЕСЕПТЕУ ҚАЖЕТ)[^\]]*\]",
        re.IGNORECASE,
    )
    document_quality._ENTITY_RE = re.compile(
        r"\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ИП|ЖК|ЖШС|АҚ|РМК|РММ|КММ|КМК)\b|\b(?:БИН|БСН)\b|"
        r"товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|"
        r"жауапкершілігі\s+шектеулі\s+серіктестік|акционерн\w*\s+обществ\w*|акционерлік\s+қоғам",
        re.IGNORECASE,
    )
    document_quality._GENERIC_COURT_MARKERS = tuple(document_quality._GENERIC_COURT_MARKERS) + (
        "соттың нақты атауы",
        "тиісті сот",
        "тұрғылықты жері бойынша",
        "орналасқан жері бойынша",
    )

    # Senior deterministic checks: same risks, Kazakh morphology/abbreviations.
    senior._ENTITY_RE = re.compile(
        r"\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ОО|ЖШС|АҚ|РМК|РММ|КММ|КМК)\b|\b(?:БИН|БСН)\b|"
        r"товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|жауапкершілігі\s+шектеулі\s+серіктестік|"
        r"акционерн\w*\s+обществ\w*|акционерлік\s+қоғам",
        re.IGNORECASE,
    )
    senior._ENTREPRENEUR_RE = re.compile(
        r"\b(?:ИП|ЖК)\b|индивидуальн\w*\s+предпринимател\w*|жеке\s+кәсіпкер|жеке\s+кәсіпкерлік",
        re.IGNORECASE,
    )
    senior._INDIVIDUAL_RE = re.compile(r"\b(?:ИИН|ЖСН)\b|дата\s+рождения|туған\s+күн", re.IGNORECASE)
    senior._CORPORATE_RE = re.compile(r"корпоративн\w*\s+спор|корпоративтік\s+дау", re.IGNORECASE)
    senior._ECONOMIC_COURT_RE = re.compile(
        r"специализированн\w*\s+межрайонн\w*\s+экономическ\w*\s+суд|\bСМЭС\b|"
        r"мамандандырылған\s+ауданаралық\s+экономикалық\s+сот",
        re.IGNORECASE,
    )
    senior._ARTICLE_27_RE = re.compile(r"(?:(?:статья|ст\.)\s*27\b|\b27\s*[-–]?\s*бап)", re.IGNORECASE)
    senior._MORAL_REQUEST_RE = re.compile(r"моральн\w*\s+вред|моральдық\s+зиян", re.IGNORECASE)
    senior._MORAL_FACT_RE = re.compile(
        r"нервн\w*|стресс\w*|переживан\w*|моральн\w*\s+страдан\w*|нравственн\w*\s+страдан\w*|"
        r"физическ\w*\s+страдан\w*|ухудшен\w*\s+(?:здоров|самочувств)|бессонниц\w*|"
        r"күйзеліс\w*|уайым\w*|жан\s+азаб\w*|моральдық\s+зардап\w*|денсаулық\w*\s+нашар",
        re.IGNORECASE,
    )
    senior._BLANK_RE = re.compile(
        r"_{3,}|\[(?:ТРЕБУЕТ|НЕИЗВЕСТНО|НАҚТЫЛАУ ҚАЖЕТ|ТЕКСЕРУ ҚАЖЕТ|ЕСЕПТЕУ ҚАЖЕТ)[^\]]*\]",
        re.IGNORECASE,
    )

    # Make the legal-basis-vs-relief check understand the same core Kazakh
    # institutions instead of silently switching itself off on Kazakh prose.
    legal_basis_fit._CATEGORY_PATTERNS = tuple(legal_basis_fit._CATEGORY_PATTERNS) + (
        ("work_acceptance", (r"жұмыс\w*\s+нәтиже\w*\s+қабыл", r"қабылдау\s+акті", r"орындалған\s+жұмыс\w*\s+қабыл")),
        ("contract_withdrawal", (r"шарттан\s+бас\s+тарт", r"шартты\s+бұз", r"алдын\s+ала\s+төлем\w*.{0,60}қайтар")),
        ("contractor_liability", (r"мердігер\w*.{0,80}(?:орындама|мерзім|кешіктір|бұз)", r"міндеттем\w*\s+орындама")),
        ("unjust_enrichment", (r"негізсіз\s+баю", r"заңды\s+негіз\w*.{0,50}(?:жоқ|жойыл)")),
        ("loan_repayment", (r"қарыз\w*", r"заем\w*", r"қолхат\w*", r"қарыз\s+сомасын\s+қайтар")),
        ("damages", (r"залал\w*", r"зиян\w*.{0,30}өтеу", r"нақты\s+залал")),
        ("penalty", (r"тұрақсыздық\s+айыб", r"өсімпұл", r"айыппұл")),
        ("procedure", (r"соттылық", r"мемлекеттік\s+баж", r"талап\s+қою\s+арыз\w*.{0,30}(?:нысан|мазмұн)", r"\bапк\b")),
    )
    original_detect_relief = legal_basis_fit.detect_relief

    def detect_relief_bilingual(requests: list[str], context_lines: list[str] | None = None):
        result = original_detect_relief(requests, context_lines)
        if result is not None:
            return result
        prayer = " ".join(str(item) for item in requests or []).lower()
        background = " ".join(str(item) for item in context_lines or []).lower()
        both = prayer + "\n" + background
        if not re.search(r"өндіріп\s+ал|қайтар|өтеу", prayer):
            return None
        prepayment = bool(re.search(r"алдын\s+ала\s+төлем|аванс|кепілпұл", both))
        works = bool(re.search(r"жұмыс|мердігер|жөндеу|құрылыс|монтаж", both))
        goods = bool(re.search(r"тауар|жеткіз", both))
        loan = bool(re.search(r"қарыз|заем|қолхат", both))
        if prepayment and works:
            return legal_basis_fit.PREPAYMENT_REFUND_WORKS
        if prepayment and goods:
            return legal_basis_fit.PREPAYMENT_REFUND_GOODS
        if loan:
            return legal_basis_fit.DEBT_RECOVERY_LOAN
        if re.search(r"залал|зиян", prayer):
            return legal_basis_fit.DAMAGES_RECOVERY
        return None

    legal_basis_fit.detect_relief = detect_relief_bilingual

    # Professional finalizer: keep source-bound propositions, but present the
    # article label / linking phrase in Kazakh when the selected language is kk.
    original_verified_basis = finalizer._verified_legal_basis

    def verified_legal_basis_bilingual(research: Any) -> list[str]:
        if current_language() != KK:
            return original_verified_basis(research)
        result: list[str] = []
        for line in research.verified_claims:
            if finalizer._COURT_SOURCE_RE.search(line):
                continue
            match = finalizer._VERIFIED_LINE_RE.search(line)
            if not match:
                continue
            statement = " ".join(match.group("statement").split()).strip(" .")
            article = " ".join(match.group("article").split()).strip(" .")
            if not statement or not article or not _ARTICLE_BILINGUAL.search(article):
                continue
            rendered = f"{statement}. Құқықтық негіз: {_article_to_kk(article)}."
            if rendered not in result:
                result.append(rendered)
        return result

    finalizer._verified_legal_basis = verified_legal_basis_bilingual
    finalizer._MORAL_RE = re.compile(r"моральн\w*\s+вред|моральдық\s+зиян|моральдық\s+залал", re.IGNORECASE)
    finalizer._SUBJECTIVE_RE = re.compile(
        r"переживан\w*|стресс\w*|нервн\w*|нравственн\w*\s+страдан\w*|моральн\w*\s+страдан\w*|"
        r"физическ\w*\s+страдан\w*|бессонниц\w*|ухудшен\w*\s+(?:здоров|самочувств)|"
        r"күйзеліс\w*|уайым\w*|жан\s+азаб\w*|моральдық\s+зардап\w*",
        re.IGNORECASE,
    )
    finalizer._PROCESS_MOTION_RE = re.compile(
        r"^(?:вызвать|допросить|истребовать|приобщить|назначить\s+экспертиз|обеспечить\s+иск|"
        r"шақыру|жауап\s+алу|сұратып\s+алу|қоса\s+тіркеу|сараптама\s+тағайындау|талапты\s+қамтамасыз\s+ету)",
        re.IGNORECASE,
    )
    finalizer._TERMINATION_RE = re.compile(
        r"расторг|прекращен|прекратить\s+договор|признать\s+договор\s+прекращ|"
        r"шартты\s+бұз|шарттан\s+бас\s+тарт|шарт\w*\s+тоқтат",
        re.IGNORECASE,
    )
    finalizer._STATE_DUTY_RE = re.compile(r"пошлин|мемлекеттік\s+баж", re.IGNORECASE)
    finalizer._COST_RE = re.compile(r"судебн\w*\s+расход|расход\w*\s+по\s+оплат|сот\s+шығын", re.IGNORECASE)
    finalizer._ALTERNATIVE_RE = re.compile(r"альтернативн|баламалы", re.IGNORECASE)
    finalizer._DISTRICTS.update(
        {
            "алатау": "Алатауский",
            "алмалы": "Алмалинский",
            "әуезов": "Ауэзовский",
            "ауезов": "Ауэзовский",
            "бостандық": "Бостандыкский",
            "жетісу": "Жетысуский",
            "жетысу": "Жетысуский",
            "медеу": "Медеуский",
            "наурызбай": "Наурызбайский",
            "түрксіб": "Турксибский",
            "турксіб": "Турксибский",
        }
    )

    # The quality hotfix transfers missing VERIFIED articles before scoring.
    # Keep that transfer in Kazakh instead of injecting a Russian sentence.
    def ensure_verified_articles_bilingual(research: Any, draft: Any) -> None:
        existing = "\n".join(draft.legal_basis).lower()
        additions: list[str] = []
        for line in research.verified_claims:
            parsed = hotfix._verified_statement_and_article(str(line))
            if parsed is None:
                continue
            statement, article = parsed
            if article.lower() in existing or _article_to_kk(article).lower() in existing:
                continue
            if current_language() == KK:
                additions.append(f"{statement}. Құқықтық негіз: {_article_to_kk(article)}.")
            else:
                additions.append(f"{statement}. Основание: {article}.")
            existing += "\n" + article.lower()
            if len(additions) >= 5:
                break
        if additions:
            draft.legal_basis.extend(additions)

    hotfix._ensure_verified_articles = ensure_verified_articles_bilingual

    citation_audit._korgan_kazakh_bridge_installed = True
