from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.legal_types import ClaimDraft, VerificationStatus

_GPK_148_RE = re.compile(
    r"(?i)(?:(?:(?:статья|статьи|ст\.)\s*148\b|148\s*[-–]?\s*бап\b).{0,120}"
    r"(?:ГПК|АПК|гражданск\w*\s+процессуальн\w*|азаматтық\s+процестік\w*)|"
    r"(?:ГПК|АПК|гражданск\w*\s+процессуальн\w*|азаматтық\s+процестік\w*).{0,120}"
    r"(?:(?:статья|статьи|ст\.)\s*148\b|148\s*[-–]?\s*бап\b))"
)
_NONPAYMENT_RE = re.compile(r"(?i)(?:неоплат\w*|не\s+оплат\w*|задолженн\w*|непогаш\w*\s+долг\w*|долг\w*)")
_SELF_PRETRIAL_EVIDENCE_RE = re.compile(
    r"(?i)(?:подтвержд\w*|отраж[её]н\w*).{0,180}(?:претензи\w*\s+истц\w*|претензи\w*\s+талап\s+қоюш\w*)|"
    r"(?:претензи\w*\s+истц\w*|претензи\w*\s+талап\s+қоюш\w*).{0,180}(?:подтвержд\w*|отраж[её]н\w*)"
)
_UNOPPOSED_RE = re.compile(
    r"(?i)[,;.]?\s*(?:(?:и|а\s+также)\s+)?(?:данн\w*\s+обстоятельств\w*\s+)?"
    r"не\s+опровергнут\w*\s+ответчик\w*.*$"
)
_SELF_EVIDENCE_TAIL_RE = re.compile(
    r"(?i)[,;.]?\s*(?:данн\w*\s+факт\w*\s+)?(?:подтвержд\w*|отраж[её]н\w*).{0,220}"
    r"(?:претензи\w*\s+истц\w*|претензи\w*\s+талап\s+қоюш\w*).*$"
)
_COST_TERM_RE = re.compile(
    r"(?i)(?:судебн\w*\s+расход\w*|расход\w*\s+на\s+(?:оплат\w*\s+)?(?:помощ\w*|представител\w*)|"
    r"сот\s+шығын\w*|өкіл\w*\s+шығын\w*)"
)
_COST_INTENT_RE = re.compile(
    r"(?i)(?:взыск\w*|прошу\b|требу\w*|өндір\w*|сұрай\w*|талап\s+ет\w*)"
)
_COST_NEGATION_RE = re.compile(
    r"(?i)(?:не\s+(?:прошу|требу\w*|взыск\w*)|не\s+подлеж\w*\s+взыск\w*|"
    r"без\s+(?:взыскания\s+)?судебн\w*\s+расход\w*|сұрамаймын|талап\s+етпеймін|өндір\w*маймын)"
)
_COST_REQUEST_RE = _COST_TERM_RE
_PRETRIAL_DATE_RE = re.compile(
    r"(?is)(?:досудебн\w*\s+претензи\w*|претензи\w*|сотқа\s+дейінгі\s+талап\w*|талап\s+хат\w*)"
    r".{0,100}?(\d{2}[./-]\d{2}[./-]\d{4})"
)
_KK_DOCUMENT_RE = re.compile(
    r"(?i)(?:талап\s+қоюшы|жауапкер|өндіріп\s+алу|мемлекеттік\s+баж|сот\s+шығын|"
    r"тұрақсыздық\s+айыб|сотқа\s+дейінгі\s+талап)"
)


def _add_filing_action(draft: ClaimDraft, message: str) -> None:
    note = FILING_ACTION_PREFIX + message
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)
    draft.status = VerificationStatus.NEEDS_VERIFICATION


def _document_language(case_context: str, draft: ClaimDraft, explicit: str | None) -> str:
    if explicit in {"ru", "kk"}:
        return explicit
    text = "\n".join(
        [case_context or "", draft.title or "", *draft.facts, *draft.requests]
    )
    return "kk" if _KK_DOCUMENT_RE.search(text) else "ru"


def _explicit_cost_requested(case_context: str) -> bool:
    """Detect an affirmative judicial-cost request in either RU or KK word order."""
    for segment in re.split(r"(?<=[.!?])\s+|\n+", case_context or ""):
        text = segment.strip()
        if not text or not _COST_TERM_RE.search(text) or not _COST_INTENT_RE.search(text):
            continue
        if _COST_NEGATION_RE.search(text):
            continue
        return True
    return False


def remove_form_article_from_material_basis(draft: ClaimDraft) -> None:
    """Article 148 GPK/APK governs claim form; it is not a debt/penalty legal basis."""
    draft.legal_basis = [
        line for line in draft.legal_basis if not _GPK_148_RE.search(str(line or ""))
    ]


def remove_circular_nonpayment_evidence(draft: ClaimDraft, *, language: str = "ru") -> None:
    """A claimant's own demand letter cannot prove that the debtor did not pay."""
    cleaned: list[str] = []
    found = False
    for raw in draft.facts:
        text = str(raw or "").strip()
        if not text:
            continue
        if _NONPAYMENT_RE.search(text) and _SELF_PRETRIAL_EVIDENCE_RE.search(text):
            found = True
            text = _SELF_EVIDENCE_TAIL_RE.sub("", text).strip(" ,;.")
        if _NONPAYMENT_RE.search(text) and _UNOPPOSED_RE.search(text):
            found = True
            text = _UNOPPOSED_RE.sub("", text).strip(" ,;.")
        if text:
            if text[-1] not in ".!?":
                text += "."
            cleaned.append(text)
    draft.facts = cleaned
    if found:
        if language == "kk":
            message = (
                "төлемнің болмауын сыртқы/екіжақты дәлелмен растау: банк көшірмесі, салыстыру актісі немесе өзге бастапқы құжат; "
                "талап қоюшының өз талабы төлем жасалмағанын дәлелдеу ретінде пайдаланылмайды."
            )
        else:
            message = (
                "подтвердить отсутствие оплаты внешним/двусторонним доказательством: банковской выпиской, актом сверки либо иным первичным документом; "
                "собственная претензия истца не используется как доказательство неоплаты."
            )
        _add_filing_action(draft, message)


def restore_explicit_cost_request(case_context: str, draft: ClaimDraft, *, language: str = "ru") -> None:
    """Do not silently lose a source-requested judicial-cost remedy after an LLM repair."""
    if not _explicit_cost_requested(case_context):
        return
    if _COST_REQUEST_RE.search("\n".join(str(item) for item in draft.requests)):
        return
    if language == "kk":
        draft.requests.append(
            "Жауапкерден талап қоюшының пайдасына құжаттармен расталған сот шығындарын өндіріп алу."
        )
    else:
        draft.requests.append(
            "Взыскать с ответчика в пользу истца документально подтвержденные судебные расходы."
        )


def flag_same_day_pretrial_risk(case_context: str, draft: ClaimDraft, *, language: str = "ru") -> None:
    """A demand dated on filing day needs an explicit pre-trial timing check."""
    today = datetime.now(ZoneInfo("Asia/Almaty")).date()
    for match in _PRETRIAL_DATE_RE.finditer(case_context or ""):
        raw = match.group(1).replace("/", ".").replace("-", ".")
        try:
            demand_date = datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError:
            continue
        if demand_date == today:
            if language == "kk":
                message = (
                    "сотқа дейінгі талап талап қою дайындалған күнімен даталанған; сотқа берер алдында шарттағы/заңдағы жауап мерзімі өткенін және жіберу/тапсыру дәлелі бар екенін тексеру."
                )
            else:
                message = (
                    "досудебная претензия датирована днем подготовки иска; до подачи проверить, истек ли обязательный договорный/законный срок для ответа и имеется ли доказательство направления/вручения."
                )
            _add_filing_action(draft, message)
            return


def enforce_claim_release_invariants(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str | None = None,
) -> None:
    """Final zero-model invariants that must survive every drafting/repair pass."""
    active_language = _document_language(case_context, draft, language)
    remove_form_article_from_material_basis(draft)
    remove_circular_nonpayment_evidence(draft, language=active_language)
    restore_explicit_cost_request(case_context, draft, language=active_language)
    flag_same_day_pretrial_risk(case_context, draft, language=active_language)
    draft.verification_notes = list(dict.fromkeys(str(item) for item in draft.verification_notes if str(item).strip()))
