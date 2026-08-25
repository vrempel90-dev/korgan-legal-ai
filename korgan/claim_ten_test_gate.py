"""Claude-style ten-test objective for Kazakhstan debt claims.

This layer is deliberately narrow: it strengthens civil money claims without
changing models, legal-source policy, payment/Telegram flow, consultations, or
runtime routing.  It reuses the existing exemplar architecture repair call
instead of adding another model round, so quality improves without a latency
penalty.

Two literal clauses from the external rubric are legally impossible if applied
word-for-word: court costs are procedural (they cannot truthfully be grounded by
an unrelated Civil Code article), and court costs do not become part of the
price of claim merely because they are requested.  The gate therefore preserves
the intended binary checks while keeping those two points legally correct:
material-law support is mandatory for substantive remedies; state duty and
representative costs require procedural support, and claim price is reconciled
to substantive property remedies only.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from korgan.claim_money_ledger import build_claim_money_ledger
from korgan.legal_calc import claimant_is_individual, parse_amount_kzt
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

_DATA = "[ДАННЫЕ:"
_VERIFY = "[СВЕРИТЬ:"

_PRINCIPAL_RE = re.compile(
    r"(?i)(?:основн\w*\s+долг\w*|задолженн\w*|долг\w*|стоимост\w*\s+(?:работ|услуг|товар)|"
    r"оплат\w*\s+(?:работ|услуг|товар)|предоплат\w*|аванс\w*|берешек\w*|борыш\w*)"
)
_PENALTY_RE = re.compile(
    r"(?i)(?:неустойк\w*|пен(?:я|и|ю|ей|е)\b|процент\w*\s+за\s+просроч\w*|"
    r"стать(?:я|и|ей|ю)\s*353\b|ст\.\s*353\b|өсімпұл\w*|тұрақсыздық\s+айыб\w*)"
)
_DUTY_RE = re.compile(r"(?i)(?:госпошлин\w*|государственн\w*\s+пошлин\w*|мемлекеттік\s+баж)")
_REP_RE = re.compile(r"(?i)(?:расход\w*.{0,80}(?:представител|юрист|юридическ)|(?:представител|юрист|юридическ).{0,80}расход\w*)")
_RECOVERY_RE = re.compile(r"(?i)(?:взыска\w*|взыскан\w*|өндір\w*|требован\w*)")
_TRANSITION_RE = re.compile(r"(?i)(?:на\s+основании\s+изложенного\s+)?ПРОШУ\s+СУД\s*:?|СОТТАН\s+СҰРАЙМЫН\s*:?")
_LEGAL_ENTITY_RE = re.compile(r"(?i)\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ОО)\b|товариществ\w*\s+с\s+ограниченн\w*\s+ответственност")
_IDENTIFIER_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_CONTRACT_NO_RE = re.compile(r"(?i)(?:договор|шарт)\s*№\s*([^\s,;.]+)")
_CITY_RE = re.compile(r"(?i)\bг\.\s*([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z-]{2,})")
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
_DATE_RANGE_RE = re.compile(
    r"(?i)\bс\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})\s+по\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
)
_USEFUL_FACT_RE = re.compile(
    r"(?i)(?:договор|шарт|акт|работ|услуг|товар|исполн|обязат|оплат|долг|задолж|просроч|"
    r"неустой|пен\w*|процент|претензи|уведом|получ|направ|зарегистрир|место\s+нахожд|"
    r"подсуд|госпошлин|представител|расход|расч[её]т|цена\s+иска|доказат)"
)
_DOC_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("договор", re.compile(r"(?i)\bдоговор\w*\b|\bшарт\w*\b")),
    ("акт", re.compile(r"(?i)\bакт\w*\b")),
    ("претензия", re.compile(r"(?i)\bпретензи\w*\b|\bталап\w*\b")),
    ("платежный документ", re.compile(r"(?i)\bквитанц\w*\b|платежн\w*\s+поручен\w*|төлем\w*\s+құжат\w*")),
    ("доверенность", re.compile(r"(?i)\bдоверенност\w*\b|сенімхат\w*")),
)


TEN_TEST_OBJECTIVE = r"""
ЦЕЛЕВАЯ ФУНКЦИЯ ИСКА: документ должен пройти десять бинарных тестов. Гладкость текста вторична.
Т1. Каждое МАТЕРИАЛЬНО-ПРАВОВОЕ требование (долг, неустойка/проценты, иной способ защиты) имеет конкретную VERIFIED материальную норму ГК РК. Госпошлина и расходы представителя — судебные расходы: их нельзя ложно обосновывать ГК, для них нужна применимая VERIFIED процессуальная норма.
Т2. У каждой процитированной нормы есть конкретный факт-якорь из материалов. Никаких тематически близких норм без факта.
Т3. Каждый абзац фактов ведет к конкретному требованию, расчету, доказательству нарушения либо подсудности. Не удаляй полезный абзац ради теста — перепиши связь.
Т4. Для денежного иска о взыскании долга просительная часть должна явно содержать: основной долг; заявленную пользователем неустойку либо проценты за просрочку; госпошлину; расходы на представителя. Если факт оплаты/сумма судебных расходов отсутствуют, сохрани позицию честным маркером [ДАННЫЕ: ...], не выдумывай расход.
Т5. Ни одного нового БИН/ИИН, адреса, города стороны, номера договора, даты, суммы либо обстоятельства. Расчетная величина допустима только как явный расчет из входных данных.
Т6. Структурный блок и переход к просительной части встречаются ровно один раз. Повтор не удаляй молча: перепиши повторный фрагмент в содержательный абзац без второго заголовка.
Т7. Цена иска равна сумме самостоятельных ИМУЩЕСТВЕННЫХ материально-правовых требований. Судебные расходы в цену иска не включай. Госпошлина рассчитывается от этой цены. Неустойка/проценты имеют явную формулу, период и результат; при нехватке исходных данных — [ДАННЫЕ: ...].
Т8. Двусторонняя сверка документов: каждый документ, упомянутый как доказательство, есть в приложениях; каждое приложение связано с текстом. Не придумывай документ только ради списка.
Т9. Хронология непротиворечива; период просрочки не начинается до наступления срока исполнения; если срок/рабочие дни нельзя надежно определить из материалов — [СВЕРИТЬ: дата начала просрочки]. Срок исковой давности не объявляй соблюденным без проверяемых дат.
Т10. Любой отсутствующий пользовательский факт закрывается только [ДАННЫЕ: ...]; любой юридический/расчетный вопрос, требующий проверки, — [СВЕРИТЬ: ...]. Никакой правдоподобной подстановки и никакого умолчания.
ШТРАФ НОЛЬ: не добавляй факты; не удаляй фрагменты вместо переписывания; не называй номер нормы без VERIFIED — при сомнении используй [СВЕРИТЬ: ...].
Перед возвратом выполни фактическую сверку Т1–Т10. Самооценка без конкретной опоры в тексте не считается исправлением.
""".strip()


@dataclass(frozen=True, slots=True)
class TenTestResult:
    passed: dict[str, bool]
    evidence: dict[str, str]

    @property
    def score(self) -> int:
        return sum(1 for value in self.passed.values() if value)

    @property
    def failed(self) -> list[str]:
        return [name for name, ok in self.passed.items() if not ok]


def _text(draft: ClaimDraft) -> str:
    return "\n".join([
        draft.court,
        *draft.claimant,
        *draft.defendant,
        draft.price_of_claim,
        draft.state_duty,
        draft.late_interest,
        *draft.facts,
        *draft.legal_basis,
        *draft.requests,
        *draft.attachments,
    ])


def _debt_claim(case_context: str, draft: ClaimDraft) -> bool:
    source = "\n".join([case_context or "", draft.title or "", *draft.requests])
    return bool(_RECOVERY_RE.search(source) and _PRINCIPAL_RE.search(source))


def _request_has(regex: re.Pattern[str], draft: ClaimDraft) -> bool:
    return any(regex.search(str(item or "")) for item in draft.requests or [])


def _paid_duty_fact(case_context: str) -> bool:
    low = case_context or ""
    return bool(re.search(r"(?is)(?:уплачен|оплачен|квитанц|платежн\w*\s+поручен).{0,120}(?:госпошлин|государственн\w*\s+пошлин)|(?:госпошлин|государственн\w*\s+пошлин).{0,120}(?:уплачен|оплачен|квитанц|платежн\w*\s+поручен)", low))


def _paid_rep_fact(case_context: str) -> bool:
    return bool(re.search(r"(?is)(?:представител|юрист|юридическ).{0,180}(?:уплачен|оплачен|платеж|тенге|тг|₸)|(?:уплачен|оплачен|платеж).{0,180}(?:представител|юрист|юридическ)", case_context or ""))


def _normalize_gap_marker(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\[ТРЕБУЕТ\s+УТОЧНЕНИЯ\s*:\s*([^\]]+)\]", r"[ДАННЫЕ: \1]", text, flags=re.I)
    text = re.sub(r"\[ТРЕБУЕТ\s+ДОБАВИТЬ\s*:\s*([^\]]+)\]", r"[ДАННЫЕ: \1]", text, flags=re.I)
    text = re.sub(r"\[ТРЕБУЕТ\s+ПРОВЕРКИ\s*:\s*([^\]]+)\]", r"[СВЕРИТЬ: \1]", text, flags=re.I)
    text = re.sub(r"\[ТРЕБУЕТ\s+РАСЧ[ЕЁ]ТА\s+ГОСПОШЛИНЫ\]", "[ДАННЫЕ: размер государственной пошлины после определения цены иска]", text, flags=re.I)
    text = re.sub(r"\[ТРЕБУЕТ\s+РАСЧ[ЕЁ]ТА\s+ЦЕНЫ\s+ИСКА\]", "[ДАННЫЕ: цена иска после определения всех денежных требований]", text, flags=re.I)
    return text


def _party_gap_markers(items: list[str], *, role: str, case_context: str) -> list[str]:
    result = [_normalize_gap_marker(str(item)) for item in items if str(item).strip()]
    if not result:
        return [f"[ДАННЫЕ: данные {role}]"]
    visible = "\n".join(result)
    source = case_context or ""
    legal_entity = bool(_LEGAL_ENTITY_RE.search(visible) or _LEGAL_ENTITY_RE.search(source))
    if legal_entity:
        if "БИН" not in visible.upper() and not re.search(r"(?i)\bБИН\b.{0,40}\d{12}", source):
            result.append(f"[ДАННЫЕ: БИН {role}]")
    else:
        if "ИИН" not in visible.upper() and not re.search(r"(?i)\bИИН\b.{0,40}\d{12}", source):
            result.append(f"[ДАННЫЕ: ИИН {role}]")
    if not re.search(r"(?i)(?:адрес|место\s+нахождения|место\s+жительства|улиц|проспект|мкр\.?|микрорайон)", visible):
        result.append(f"[ДАННЫЕ: адрес {role}]")
    return list(dict.fromkeys(result))


def ensure_cost_slots(case_context: str, draft: ClaimDraft) -> None:
    """Make T4 structurally complete without fabricating incurred expenses."""
    if not _debt_claim(case_context, draft):
        return
    if not _request_has(_DUTY_RE, draft):
        duty_amount = parse_amount_kzt(str(draft.state_duty or ""))
        if duty_amount is not None and duty_amount >= 0:
            suffix = "" if _paid_duty_fact(case_context) else " [ДАННЫЕ: документ, подтверждающий фактическую уплату государственной пошлины]"
            draft.requests.append(
                f"Взыскать с ответчика расходы по уплате государственной пошлины в размере {duty_amount:,} тенге.{suffix}".replace(",", " ")
            )
        else:
            draft.requests.append(
                "Взыскать с ответчика расходы по уплате государственной пошлины "
                "[ДАННЫЕ: размер государственной пошлины и документ, подтверждающий ее уплату]."
            )
    elif not _paid_duty_fact(case_context):
        draft.requests = [
            (str(item) if not _DUTY_RE.search(str(item)) or _DATA in str(item) else str(item).rstrip(". ") + " [ДАННЫЕ: документ, подтверждающий фактическую уплату государственной пошлины].")
            for item in draft.requests
        ]

    if not _request_has(_REP_RE, draft):
        if _paid_rep_fact(case_context):
            draft.requests.append(
                "Взыскать с ответчика документально подтвержденные расходы на представителя "
                "[ДАННЫЕ: точная сумма расходов на представителя]."
            )
        else:
            draft.requests.append(
                "Взыскать с ответчика расходы на представителя "
                "[ДАННЫЕ: размер фактически понесенных расходов на представителя и подтверждающие документы]."
            )
    elif not _paid_rep_fact(case_context):
        draft.requests = [
            (str(item) if not _REP_RE.search(str(item)) or _DATA in str(item) else str(item).rstrip(". ") + " [ДАННЫЕ: размер фактически понесенных расходов и подтверждающие документы].")
            for item in draft.requests
        ]


def ensure_gap_markers(case_context: str, draft: ClaimDraft) -> None:
    draft.court = _normalize_gap_marker(draft.court) or "[ДАННЫЕ: точное наименование суда]"
    draft.claimant = _party_gap_markers(draft.claimant, role="истца", case_context=case_context)
    draft.defendant = _party_gap_markers(draft.defendant, role="ответчика", case_context=case_context)
    draft.price_of_claim = _normalize_gap_marker(draft.price_of_claim) or "[ДАННЫЕ: цена иска]"
    draft.state_duty = _normalize_gap_marker(draft.state_duty) or "[ДАННЫЕ: размер государственной пошлины]"
    draft.late_interest = _normalize_gap_marker(draft.late_interest)
    for attr in ("facts", "legal_basis", "requests", "attachments", "verification_notes"):
        values = list(getattr(draft, attr, []) or [])
        setattr(draft, attr, [_normalize_gap_marker(str(item)) for item in values])


def rewrite_duplicate_transitions(draft: ClaimDraft) -> None:
    """Keep substance but forbid a second petition heading inside model prose."""
    replacement = "Из изложенных обстоятельств следует необходимость заявленных способов судебной защиты."
    for attr in ("facts", "legal_basis"):
        values: list[str] = []
        for raw in list(getattr(draft, attr, []) or []):
            text = str(raw)
            if _TRANSITION_RE.search(text):
                text = _TRANSITION_RE.sub(replacement, text)
            values.append(text)
        setattr(draft, attr, values)
    draft.requests = [
        _TRANSITION_RE.sub("Просительная часть:", str(item)) if _TRANSITION_RE.search(str(item)) else str(item)
        for item in draft.requests or []
    ]


def _unknown_party_facts(case_context: str, draft: ClaimDraft) -> list[str]:
    body = "\n".join([*draft.claimant, *draft.defendant, *draft.facts])
    source = case_context or ""
    problems: list[str] = []
    for identifier in _IDENTIFIER_RE.findall(body):
        if identifier not in source:
            problems.append(f"12-значный идентификатор {identifier} отсутствует во входных данных")
    for number in _CONTRACT_NO_RE.findall(body):
        if number and number not in source:
            problems.append(f"номер договора {number} отсутствует во входных данных")
    for city in _CITY_RE.findall("\n".join([*draft.claimant, *draft.defendant])):
        if city.casefold() not in source.casefold():
            problems.append(f"город стороны {city} отсутствует во входных данных")
    for line in [*draft.claimant, *draft.defendant]:
        if re.search(r"(?i)\bадрес\b\s*:\s*[^\[]", line) and line.casefold() not in source.casefold():
            problems.append("адрес стороны отсутствует во входных данных")
    return list(dict.fromkeys(problems))


def _line_has_anchor(line: str, case_context: str) -> bool:
    low = line.casefold()
    source = case_context.casefold()
    if not re.search(r"(?i)(?:стать(?:я|и|ей|ю)|ст\.)\s*\d+", line):
        return True
    if any(x in low for x in ("филиал", "представительств")):
        return "филиал" in source or "представительств" in source
    if _PENALTY_RE.search(line):
        return bool(_PENALTY_RE.search(case_context))
    if any(x in low for x in ("подсуд", "месту нахождения ответчика", "территориальн")):
        return bool(re.search(r"(?i)(?:зарегистрир|место\s+нахождения|адрес|город|г\.)", case_context))
    if any(x in low for x in ("договор", "подряд", "работ", "услуг", "обязательств", "оплат", "долг", "задолж")):
        return bool(re.search(r"(?i)(?:договор|подряд|работ|услуг|оплат|долг|задолж|акт)", case_context))
    return bool(re.search(r"(?i)(?:договор|обязательств|нарушен|правоотнош|акт|оплат|долг|задолж)", case_context))


def _doc_alignment(case_context: str, draft: ClaimDraft) -> tuple[bool, str]:
    narrative = "\n".join([case_context or "", *draft.facts])
    attachments = "\n".join(draft.attachments or [])
    missing: list[str] = []
    orphan: list[str] = []
    for label, regex in _DOC_TYPES:
        in_text = bool(regex.search(narrative))
        in_attachments = bool(regex.search(attachments))
        if in_text and not in_attachments:
            missing.append(label)
        if in_attachments and not in_text:
            orphan.append(label)
    if missing or orphan:
        return False, f"не хватает в приложениях: {missing or 'нет'}; приложения без текстовой опоры: {orphan or 'нет'}"
    return True, "все типы упомянутых документов двусторонне согласованы"


def _parse_date(value: str):
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
    except ValueError:
        return None


def _chronology_ok(case_context: str, draft: ClaimDraft) -> tuple[bool, str]:
    combined = "\n".join([case_context or "", *draft.facts, draft.late_interest or ""])
    for match in _DATE_RANGE_RE.finditer(combined):
        start = _parse_date(match.group(1))
        end = _parse_date(match.group(2))
        if start and end and end < start:
            return False, f"период {match.group(1)}–{match.group(2)} имеет обратный порядок"
    delay_dates: list[Any] = []
    for segment in re.split(r"(?<=[.!?])\s+|\n+", combined):
        if re.search(r"(?i)просроч", segment):
            delay_dates.extend(filter(None, (_parse_date(token) for token in re.findall(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}", segment))))
    if delay_dates:
        oldest = min(delay_dates)
        today = datetime.now(ZoneInfo("Asia/Almaty")).date()
        if (today - oldest).days > 3 * 366 and not re.search(r"(?i)(?:перерыв|приостанов|признан\w*\s+долг)", case_context or ""):
            return False, "по видимым датам возможен выход за общий трехлетний период; требуется отдельная проверка давности"
    return True, "обратных периодов и явного выхода за трехлетний период не обнаружено"


def evaluate_claim_ten_tests(case_context: str, research: LegalResearch, draft: ClaimDraft) -> TenTestResult:
    from korgan import claim_exemplar_architecture as arch

    debt = _debt_claim(case_context, draft)
    prayer = "\n".join(draft.requests or [])
    legal = "\n".join(draft.legal_basis or [])
    legal_articles = set().union(*(arch._articles(line) for line in draft.legal_basis)) if draft.legal_basis else set()
    material = arch._verified_material_articles(research)
    penalty_material = arch._verified_penalty_articles(research)

    substantive_ok = True
    t1_evidence: list[str] = []
    if debt and _request_has(_PRINCIPAL_RE, draft):
        supported = bool(legal_articles.intersection(material))
        substantive_ok &= supported
        t1_evidence.append("основной долг: " + ("VERIFIED material article" if supported else "нет VERIFIED material article"))
    if debt and _request_has(_PENALTY_RE, draft):
        supported = bool(legal_articles.intersection(penalty_material))
        substantive_ok &= supported
        t1_evidence.append("ответственность за просрочку: " + ("VERIFIED material article" if supported else "нет VERIFIED material article"))
    if not t1_evidence:
        t1_evidence.append("нет денежного материально-правового требования данного профиля")

    anchored_lines = [line for line in draft.legal_basis if re.search(r"(?i)(?:стать(?:я|и|ей|ю)|ст\.)\s*\d+", line)]
    unanchored = [line for line in anchored_lines if not _line_has_anchor(line, case_context)]

    useless = [line for line in draft.facts if str(line).strip() and _DATA not in str(line) and _VERIFY not in str(line) and not _USEFUL_FACT_RE.search(str(line))]

    t4 = True
    t4_parts: list[str] = []
    if debt:
        for label, regex in (("долг", _PRINCIPAL_RE), ("неустойка/проценты", _PENALTY_RE), ("госпошлина", _DUTY_RE), ("представитель", _REP_RE)):
            ok = bool(regex.search(prayer))
            t4 &= ok
            t4_parts.append(f"{label}={'да' if ok else 'нет'}")
    else:
        t4_parts.append("не денежный иск о взыскании долга — четырехпозиционный тест не применяется")

    inventions = _unknown_party_facts(case_context, draft)
    duplicate_transition = any(_TRANSITION_RE.search(str(item)) for item in [*draft.facts, *draft.legal_basis, *draft.requests])

    ledger = build_claim_money_ledger(list(draft.requests or []))
    price = parse_amount_kzt(draft.price_of_claim or "")
    marked_gap = _DATA in prayer or _VERIFY in prayer or _DATA in (draft.price_of_claim or "") or _VERIFY in (draft.price_of_claim or "")
    arithmetic_ok = bool(marked_gap or (not ledger.unresolved_requests and ((ledger.total == 0 and price is None) or ledger.total == price)))
    if debt and _request_has(_PENALTY_RE, draft) and not marked_gap:
        penalty_calc = "\n".join([*draft.facts, draft.late_interest or ""])
        arithmetic_ok &= bool(re.search(r"(?i)(?:расч[её]т|×|дн\.|дней|календарн\w*\s+дн)", penalty_calc) and _PENALTY_RE.search(penalty_calc))

    docs_ok, docs_evidence = _doc_alignment(case_context, draft)
    chrono_ok, chrono_evidence = _chronology_ok(case_context, draft)

    all_visible = _text(draft)
    legacy_gap = bool(re.search(r"\[(?:ТРЕБУЕТ|НЕИЗВЕСТНО)[^\]]*\]", all_visible, re.I))
    t10 = not legacy_gap

    passed = {
        "T1": substantive_ok,
        "T2": not unanchored,
        "T3": not useless,
        "T4": t4,
        "T5": not inventions,
        "T6": not duplicate_transition,
        "T7": arithmetic_ok,
        "T8": docs_ok,
        "T9": chrono_ok,
        "T10": t10,
    }
    evidence = {
        "T1": "; ".join(t1_evidence),
        "T2": "все процитированные нормы имеют фактический якорь" if not unanchored else f"без якоря: {unanchored[:2]}",
        "T3": "каждый фактический абзац имеет функцию" if not useless else f"нефункциональные абзацы: {useless[:2]}",
        "T4": "; ".join(t4_parts),
        "T5": "новых реквизитов/идентификаторов не найдено" if not inventions else "; ".join(inventions),
        "T6": "внутри данных нет второго перехода ПРОШУ СУД" if not duplicate_transition else "найден дублирующий переход",
        "T7": f"ledger={ledger.total}; price={price}; marked_gap={marked_gap}; unresolved={len(ledger.unresolved_requests)}",
        "T8": docs_evidence,
        "T9": chrono_evidence,
        "T10": "используются только [ДАННЫЕ]/[СВЕРИТЬ]" if not legacy_gap else "остался legacy-маркер [ТРЕБУЕТ]/[НЕИЗВЕСТНО]",
    }
    return TenTestResult(passed=passed, evidence=evidence)


def ten_test_issues(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
    ensure_cost_slots(case_context, draft)
    result = evaluate_claim_ten_tests(case_context, research, draft)
    issues: list[str] = []
    for test in result.failed:
        if test == "T10":
            # Legacy markers are normalized deterministically at export; do not
            # spend an AI repair call on typography alone.
            continue
        issues.append(f"{test}: {result.evidence[test]}")
    return issues


def finalize_visible_claim(case_context: str, research: LegalResearch | None, draft: ClaimDraft) -> TenTestResult | None:
    """Final deterministic pass immediately before DOCX rendering."""
    ensure_gap_markers(case_context, draft)
    ensure_cost_slots(case_context, draft)
    rewrite_duplicate_transitions(draft)
    if research is None:
        return None
    result = evaluate_claim_ten_tests(case_context, research, draft)
    LOGGER.info(
        "CLAIM_TEN_TEST score=%s/10 failed=%s evidence=%s",
        result.score,
        result.failed,
        {name: result.evidence[name] for name in result.failed[:4]},
    )
    if result.failed:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
    return result


def install_claim_ten_test_gate() -> None:
    """Attach the objective to existing claim architecture and final DOCX export."""
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import claim_docx
    from korgan import claim_exemplar_architecture as arch

    current_block = arch.architecture_block
    if not getattr(current_block, "_korgan_ten_test", False):
        def block_with_ten_tests(case_context: str) -> str:
            return current_block(case_context) + "\n\n" + TEN_TEST_OBJECTIVE
        block_with_ten_tests._korgan_ten_test = True  # type: ignore[attr-defined]
        arch.architecture_block = block_with_ten_tests

    current_issues = arch.architecture_issues
    if not getattr(current_issues, "_korgan_ten_test", False):
        def issues_with_ten_tests(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
            existing = current_issues(case_context, research, draft)
            added = ten_test_issues(case_context, research, draft)
            return list(dict.fromkeys([*existing, *added]))
        issues_with_ten_tests._korgan_ten_test = True  # type: ignore[attr-defined]
        arch.architecture_issues = issues_with_ten_tests

    current_status: Callable[[ClaimDraft], str] = claim_docx._document_status
    if not getattr(current_status, "_korgan_ten_test", False):
        def status_with_gap_markers(draft: ClaimDraft) -> str:
            visible = _text(draft).upper()
            if "[ДАННЫЕ:" in visible or "[СВЕРИТЬ:" in visible:
                return claim_docx.QA_PRELIMINARY
            return current_status(draft)
        status_with_gap_markers._korgan_ten_test = True  # type: ignore[attr-defined]
        claim_docx._document_status = status_with_gap_markers

    current_build = claim_docx.build_claim_docx
    if not getattr(current_build, "_korgan_ten_test", False):
        def build_with_ten_tests(draft: ClaimDraft) -> bytes:
            # Research is unavailable at renderer boundary; all legal tests have
            # already participated in the existing exemplar repair gate.  The
            # renderer owns only deterministic missing-data/cost/duplication shape.
            ensure_gap_markers("", draft)
            ensure_cost_slots("", draft)
            rewrite_duplicate_transitions(draft)
            return current_build(draft)
        build_with_ten_tests._korgan_ten_test = True  # type: ignore[attr-defined]
        claim_docx.build_claim_docx = build_with_ten_tests

    _INSTALLED = True
    LOGGER.info("Installed KORGAN claim ten-test objective: T1-T10 + zero-invention gap markers; no extra model round")
