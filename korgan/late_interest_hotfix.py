from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from korgan.legal_calc import (
    NEEDS_RATE_MARKER,
    calc_late_payment_penalty,
    format_kzt,
    gosposhlina_line,
    late_penalty_line,
    parse_amount_kzt,
)
from korgan.legal_types import ClaimDraft, LegalResearch
from korgan.state_duty_final_hotfix import (
    ProductionOpenAILegalService as _BaseProductionOpenAILegalService,
    _enforce_single_state_duty_request,
)
from korgan.verified_openai import (
    _VERIFIED_RESEARCH_SCHEMA,
    _actual_response_urls,
    _canonical_url,
)


_ARTICLE_353_RE = re.compile(r"(?<!\d)353(?!\d)")
_GK_GENERAL_MARKER = "K940001000_"

_EXPLICIT_PENALTY_PATTERNS = (
    re.compile(
        r"(?:прошу|требую|взыскать|взыщите|начислить|заявляю|добавьте|добавь)"
        r"[^.\n]{0,120}(?:неустойк\w*|ст\.?\s*353|стать\w*\s*353|"
        r"пользован\w*\s+чужими\s+деньг\w*|процент\w*\s+за\s+просроч\w*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:неустойк\w*|ст\.?\s*353|стать\w*\s*353|"
        r"пользован\w*\s+чужими\s+деньг\w*|процент\w*\s+за\s+просроч\w*)"
        r"[^.\n]{0,120}(?:взыскать|требую|прошу|начислить)",
        re.IGNORECASE,
    ),
)

_PENALTY_LINE_RE = re.compile(
    r"(?:ст\.?\s*353|стать\w*\s*353|неустойк\w*|"
    r"пользован\w*\s+чужими\s+деньг\w*|процент\w*\s+(?:по\s+денежн\w*|за\s+просроч\w*))",
    re.IGNORECASE,
)

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_DATE_TOKEN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+\d{4}(?:\s+года)?)"
)
_DUE_RE = re.compile(
    rf"(?:вернут\w*|возврат\w*|погас\w*|обязал\w*\s+вернут\w*)"
    rf"[^.\n]{{0,160}}?(?:не\s+позднее|до)\s+(?P<date>{_DATE_TOKEN})",
    re.IGNORECASE,
)

ARTICLE_353_MISSING_NOTE = (
    "Клиент заявил требование о неустойке за просрочку, но статья 353 ГК РК "
    "не прошла source-bound проверку в текущем legal research; денежное требование не добавлено."
)
DUE_DATE_MISSING_NOTE = (
    "Для расчёта неустойки по статье 353 не удалось однозначно установить срок исполнения; "
    "требуется проверить дату начала просрочки."
)
RATE_MISSING_NOTE = (
    "Базовая ставка НБ РК для даты предъявления иска не подтверждена актуальным внутренним справочником; "
    "расчёт неустойки по статье 353 не выполнен."
)


def _today_kz() -> date:
    return datetime.now(ZoneInfo("Asia/Almaty")).date()


def _explicit_penalty_requested(case_context: str) -> bool:
    return any(pattern.search(case_context or "") for pattern in _EXPLICIT_PENALTY_PATTERNS)


def _research_has_article_353(research: LegalResearch) -> bool:
    for claim in research.verified_claims:
        if _ARTICLE_353_RE.search(claim) and _GK_GENERAL_MARKER.lower() in claim.lower():
            return True
    has_article = any(_ARTICLE_353_RE.search(claim) for claim in research.verified_claims)
    has_source = any(_GK_GENERAL_MARKER.lower() in url.lower() for url in research.source_urls)
    return has_article and has_source


def _parse_date_token(raw: str) -> date | None:
    text = (raw or "").strip().lower().replace(" года", "")
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text)
    if not match:
        return None
    month = _MONTHS.get(match.group(2))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _extract_due_date(case_context: str) -> date | None:
    candidates: list[date] = []
    for match in _DUE_RE.finditer(case_context or ""):
        parsed = _parse_date_token(match.group("date"))
        if parsed and parsed not in candidates:
            candidates.append(parsed)
    return candidates[0] if len(candidates) == 1 else None


def _principal_amount(draft: ClaimDraft) -> int | None:
    """Prefer the standalone principal request over a model-written total claim price."""
    for request in draft.requests:
        if _PENALTY_LINE_RE.search(request):
            continue
        lowered = request.lower()
        if any(marker in lowered for marker in ("основн", "долг", "задолж")):
            amount = parse_amount_kzt(request)
            if amount:
                return amount
    return parse_amount_kzt(draft.price_of_claim)


def _remove_model_penalty(draft: ClaimDraft, case_context: str) -> None:
    """Do not let the model add an unrequested or unverified monetary claim."""
    principal = _principal_amount(draft)
    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_LINE_RE.search(item)]
    draft.late_interest = ""

    if principal:
        draft.price_of_claim = format_kzt(principal)
        draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
        _enforce_single_state_duty_request(draft)

    draft.title = re.sub(
        r"\s+и\s+(?:процент\w*|неустойк\w*)[^\n]*$",
        "",
        draft.title,
        flags=re.IGNORECASE,
    ).strip()


def _apply_verified_article_353(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    *,
    filing_date: date,
) -> None:
    requested = _explicit_penalty_requested(case_context)
    if not requested:
        _remove_model_penalty(draft, case_context)
        return

    if not _research_has_article_353(research):
        _remove_model_penalty(draft, case_context)
        if ARTICLE_353_MISSING_NOTE not in draft.verification_notes:
            draft.verification_notes.append(ARTICLE_353_MISSING_NOTE)
        return

    due_date = _extract_due_date(case_context)
    principal = _principal_amount(draft)
    if due_date is None or principal is None:
        _remove_model_penalty(draft, case_context)
        if DUE_DATE_MISSING_NOTE not in draft.verification_notes:
            draft.verification_notes.append(DUE_DATE_MISSING_NOTE)
        return

    start = due_date + timedelta(days=1)
    if filing_date < start:
        _remove_model_penalty(draft, case_context)
        return

    penalty = calc_late_payment_penalty(
        principal,
        start,
        filing_date,
        rate_date=filing_date,
    )
    if penalty is None:
        _remove_model_penalty(draft, case_context)
        draft.late_interest = NEEDS_RATE_MARKER
        if RATE_MISSING_NOTE not in draft.verification_notes:
            draft.verification_notes.append(RATE_MISSING_NOTE)
        return

    draft.requests = [item for item in draft.requests if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis = [item for item in draft.legal_basis if not _PENALTY_LINE_RE.search(item)]
    draft.legal_basis.append(
        "В соответствии с пунктами 1 и 2 статьи 353 Гражданского кодекса Республики Казахстан "
        "за неправомерное пользование чужими деньгами вследствие просрочки денежного обязательства "
        "подлежит уплате неустойка; при судебном взыскании кредитор вправе выбрать базовую ставку "
        "Национального Банка на день предъявления иска, вынесения решения либо фактического платежа, "
        "а неустойка начисляется по день уплаты суммы денег."
    )
    draft.late_interest = late_penalty_line(penalty)
    draft.requests.append(
        "Взыскать с ответчика в пользу истца неустойку по статье 353 ГК РК "
        f"в размере {format_kzt(penalty.amount)} за период {penalty.period()} "
        f"исходя из базовой ставки НБ РК {penalty.rate_percent:g}% на дату предъявления иска; "
        "за последующий период — по день фактической уплаты суммы долга в порядке статьи 353 ГК РК."
    )

    total = principal + penalty.amount
    draft.price_of_claim = (
        f"{format_kzt(total)} (основной долг {format_kzt(principal)} + "
        f"неустойка по статье 353 ГК РК {format_kzt(penalty.amount)} на дату подачи иска)"
    )
    draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
    _enforce_single_state_duty_request(draft)


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Claude 353/citation idea adapted to the current source-bound runtime."""

    async def _targeted_article_353_research(
        self,
        case_context: str,
        language: str,
    ) -> tuple[list[str], list[str]]:
        """Verify Article 353 through the same actual-search-URL binding as KORGAN."""
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "low",
        }]
        prompt = (
            "Отдельная узкая проверка для денежного требования в иске. Открой действующую Общую часть "
            "Гражданского кодекса Республики Казахстан на Adilet (K940001000_) и проверь статью 353. "
            "Установи, применима ли она к описанной просрочке денежного обязательства. "
            "Если применима, верни один verified_point с точным выводом, article='353' и URL реально открытой "
            "официальной страницы. Если нет или источник не подтверждён — только unverified_claims.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:24000]}"
        )
        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты source-bound юридический исследователь KORGAN. Не отвечай по памяти. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_verified_legal_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if self._is_current_official_source(url) and _GK_GENERAL_MARKER.lower() in url.lower()
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }
        claims: list[str] = []
        used_urls: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not _ARTICLE_353_RE.search(article) or not actual_url:
                continue
            claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)
        return claims, used_urls

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        research = await super().research_case(case_context, language=language)
        if not _explicit_penalty_requested(case_context) or _research_has_article_353(research):
            return research

        claims, urls = await self._targeted_article_353_research(case_context, language)
        for claim in claims:
            if claim not in research.verified_claims:
                research.verified_claims.append(claim)
        for url in urls:
            if url not in research.source_urls:
                research.source_urls.append(url)
        return research

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        _apply_verified_article_353(
            case_context,
            research,
            draft,
            filing_date=_today_kz(),
        )
        return draft
