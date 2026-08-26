from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from korgan.pretrial_money import DEFAULT_VOLUNTARY_DAYS, document_date_from_context


class PretrialStage(StrEnum):
    PRIMARY = "primary"
    REPEATED = "repeated"
    CLAIM = "claim"


_DATE = r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})"
_PRIOR_DELIVERY_PATTERNS = (
    re.compile(
        r"(?i)(?:претензи\w*|сотқа\s+дейінгі\s+талап\w*|талап\s*хат\w*)"
        r".{0,100}?(?:вручен\w*|получен\w*|доставлен\w*|табыс\w*|алын\w*)"
        r".{0,40}?" + _DATE
    ),
    re.compile(
        r"(?i)(?:вручен\w*|получен\w*|доставлен\w*|табыс\w*|алын\w*)"
        r".{0,70}?(?:претензи\w*|сотқа\s+дейінгі\s+талап\w*|талап\s*хат\w*)"
        r".{0,40}?" + _DATE
    ),
    re.compile(
        r"(?i)(?:претензи\w*|талап\w*)\s*(?:№\s*\S+\s*)?(?:от\s*)?"
        + _DATE
        + r".{0,120}?(?:вручен\w*|получен\w*|доставлен\w*|табыс\w*|алын\w*)"
    ),
)
_NO_RESPONSE_RE = re.compile(
    r"(?i)(?:ответ\w*\s+(?:не\s+)?получен\w*|ответа\s+нет|без\s+ответа|"
    r"не\s+ответил\w*|жауап\s+жоқ|жауап\s+алынба)"
)
_EXPIRED_RE = re.compile(
    r"(?i)(?:срок\w*\s+(?:ответа|рассмотрения|исполнения).{0,30}(?:ист[её]к|прош[её]л)|"
    r"досудебн\w*\s+порядок\w*.{0,30}исчерпан|"
    r"претензионн\w*\s+порядок\w*.{0,30}исчерпан|"
    r"мерзім\w*.{0,30}(?:өтті|аяқтал))"
)
_EXPLICIT_EXHAUSTED_RE = re.compile(
    r"(?i)(?:досудебн\w*|претензионн\w*)\s+порядок\w*.{0,45}"
    r"(?:исчерпан|соблюден|завершен)"
)
_PRIMARY_REQUEST_RE = re.compile(r"(?i)(?:первичн\w*\s+претензи\w*|режим\s*[:=-]?\s*первичн)")
_REPEATED_REQUEST_RE = re.compile(r"(?i)(?:повторн\w*\s+претензи\w*|режим\s*[:=-]?\s*повторн)")
_RESPONSE_TERM_RE = re.compile(
    r"(?i)(?:срок\w*.{0,70}?(?:ответ|рассмотр|претензи)|"
    r"(?:ответ|рассмотр|претензи)\w*.{0,70}?срок\w*)"
    r".{0,35}?(?P<days>\d{1,3})\s*(?:календарн\w*\s+)?дн"
)


def _match_date(match: re.Match[str]) -> date | None:
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except (ValueError, TypeError):
        return None


def prior_pretrial_delivery_date(case_context: str) -> date | None:
    text = str(case_context or "")
    for pattern in _PRIOR_DELIVERY_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _match_date(match)
            if parsed:
                return parsed
    return None


def contractual_response_days(case_context: str) -> int | None:
    match = _RESPONSE_TERM_RE.search(str(case_context or ""))
    if not match:
        return None
    try:
        days = int(match.group("days"))
    except (TypeError, ValueError):
        return None
    return days if 0 < days <= 366 else None


def requested_pretrial_stage(case_context: str) -> PretrialStage | None:
    text = str(case_context or "")
    if _PRIMARY_REQUEST_RE.search(text):
        return PretrialStage.PRIMARY
    if _REPEATED_REQUEST_RE.search(text):
        return PretrialStage.REPEATED
    return None


@dataclass(frozen=True, slots=True)
class PretrialStageDecision:
    factual_stage: PretrialStage
    template_stage: PretrialStage
    prior_delivery_date: date | None
    response_deadline: date | None
    response_absent: bool
    exhausted: bool
    requested_stage: PretrialStage | None

    @property
    def facts_above_template(self) -> bool:
        order = {
            PretrialStage.PRIMARY: 0,
            PretrialStage.REPEATED: 1,
            PretrialStage.CLAIM: 2,
        }
        return order[self.factual_stage] > order[self.template_stage]

    def prompt_block(self, *, language: str = "ru") -> str:
        delivered = self.prior_delivery_date.strftime("%d.%m.%Y") if self.prior_delivery_date else "нет"
        deadline = self.response_deadline.strftime("%d.%m.%Y") if self.response_deadline else "не установлена"
        if language == "kk":
            return (
                "KORGAN ҚҰЖАТ САТЫСЫ — ФАКТІЛЕРДЕН АНЫҚТАЛҒАН:\n"
                f"фактілік саты={self.factual_stage}; қолданылатын үлгі={self.template_stage}; "
                f"алдыңғы талаптың табыс етілу күні={delivered}; жауап мерзімі={deadline}.\n"
                "Үлгі сатысын өз бетіңше өзгертпе."
            )
        rules = [
            "KORGAN СТАДИЯ ДОКУМЕНТА — ОПРЕДЕЛЕНА КОДОМ ИЗ ФАКТОВ:",
            f"фактическая стадия={self.factual_stage}; шаблон={self.template_stage}; "
            f"предыдущая претензия вручена={delivered}; срок ответа={deadline}.",
            "Не меняй стадию самостоятельно.",
        ]
        if self.template_stage is PretrialStage.REPEATED:
            rules.append(
                "ПОВТОРНЫЙ ШАБЛОН: документ короче первичного; сослаться на первую претензию и дату вручения; "
                "не пересказывать фабулу заново; дать окончательный срок; прямо указать, что исковое заявление подготовлено."
            )
        if self.facts_above_template or self.exhausted:
            rules.append(
                "Обязательно включить отдельную строку: «По материалам дела досудебный порядок уже исчерпан.»"
            )
        return "\n".join(rules)


def decide_pretrial_stage(
    case_context: str,
    *,
    document_date: date | None = None,
    requested_stage: PretrialStage | None = None,
) -> PretrialStageDecision:
    text = str(case_context or "")
    doc_date = document_date or document_date_from_context(text)
    delivered = prior_pretrial_delivery_date(text)
    response_absent = bool(_NO_RESPONSE_RE.search(text))
    response_days = contractual_response_days(text)
    response_deadline = (
        delivered + timedelta(days=response_days or DEFAULT_VOLUNTARY_DAYS)
        if delivered is not None
        else None
    )
    expired_by_date = bool(response_deadline and doc_date > response_deadline)
    explicit_expired = bool(_EXPIRED_RE.search(text))
    explicit_exhausted = bool(_EXPLICIT_EXHAUSTED_RE.search(text))
    exhausted = bool(
        explicit_exhausted
        or (delivered and response_absent and (expired_by_date or explicit_expired))
    )

    if exhausted:
        factual = PretrialStage.CLAIM
    elif delivered:
        factual = PretrialStage.REPEATED
    else:
        factual = PretrialStage.PRIMARY

    requested = requested_stage or requested_pretrial_stage(text)
    if requested in {PretrialStage.PRIMARY, PretrialStage.REPEATED}:
        template = requested
    elif factual is PretrialStage.PRIMARY:
        template = PretrialStage.PRIMARY
    else:
        # A pretrial request can never silently turn into a claim document.
        template = PretrialStage.REPEATED

    return PretrialStageDecision(
        factual_stage=factual,
        template_stage=template,
        prior_delivery_date=delivered,
        response_deadline=response_deadline,
        response_absent=response_absent,
        exhausted=exhausted,
        requested_stage=requested,
    )
