from __future__ import annotations

import re
from typing import Pattern

import korgan.senior_claim_preflight as senior_claim_preflight
from korgan.claim_quality_gate import check_amount_consistency
from korgan.consumer_qualification import ConsumerStatus, asserts_consumer_law, consumer_status
from korgan.legal_calc import parse_all_amounts_kzt, parse_amount_kzt
from korgan.legal_types import ClaimDraft, LegalResearch

_PENALTY_REQUEST_RE = re.compile(
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)",
    re.IGNORECASE,
)
_COST_REQUEST_RE = re.compile(
    r"(?:судебн\w*\s+расход\w*|расход\w*\s+на\s+представител\w*|расход\w*\s+по\s+делу|"
    r"сот\s+шығын\w*|сот\s+шығыс\w*|өкіл\w*\s+шығын\w*)",
    re.IGNORECASE,
)
_INTENT_VERB_RE = re.compile(
    r"(?:прошу|требую|хочу|нужно|необходимо|взыска\w*|сұраймын|талап\s+етемін|өндір\w*)",
    re.IGNORECASE,
)
_NEGATION_BEFORE_RE = re.compile(r"(?:\bне\s+|\bемес\s+)$", re.IGNORECASE)
_TERM_EXCLUSION_BEFORE_RE = re.compile(
    r"(?:\bбез\b[^,.;:]{0,60}|\b(?:но\s+)?не\s+(?:взыскать|взыскивать|требовать|просить)?\s*|"
    r"\bисключая\b[^,.;:]{0,60})$",
    re.IGNORECASE,
)
_TERM_EXCLUSION_AFTER_RE = re.compile(
    r"^(?:[^,.;:]{0,40}(?:талап\s+етпеймін|сұрамаймын|өндір\w*маймын|қажет\s+емес))",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(?<!\d)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸)",
    re.IGNORECASE,
)
_RATE_RE = re.compile(r"(?<!\d)\d+(?:[.,]\d+)?\s*%")
_PERIOD_RE = re.compile(
    r"(?:\b\d+\s*(?:дн\w*|күн\w*)\b|"
    r"\b(?:с|с\s+даты|бастап)\s*\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?.{0,80}"
    r"(?:по|дейін)\s*\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)",
    re.IGNORECASE,
)
_PENALTY_WORD_RE = re.compile(
    r"(?:неустойк\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)",
    re.IGNORECASE,
)
# Сумма цифрами, возможно с расшифровкой прописью: «112 000 (сто двенадцать тысяч) тенге».
_PENALTY_SUM_RE = re.compile(
    r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:\([^)]{0,80}\)\s*)?(?:тенге|теңге|тг\b|₸)",
    re.IGNORECASE,
)
# «в размере», «в сумме» — сумма присуждаемой неустойки.
_AWARD_CUE_RE = re.compile(
    r"(?:в\s+размере|в\s+сумме|на\s+сумму|размер\w*\s+которой|мөлшерінде|сомасында)",
    re.IGNORECASE,
)
# «исходя из суммы договора» — это база начисления, а не размер неустойки.
_BASE_CUE_RE = re.compile(
    r"(?:исходя\s+из|от\s+сумм\w*|от\s+цен\w*|от\s+стоимост\w*|"
    r"сумм\w*\s+договор\w*|цен\w*\s+договор\w*|стоимост\w*\s+договор\w*|"
    r"шарт\w*\s+сомас\w*)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"[.;]")

_STATE_DUTY_CUE = r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|мемлекетт(?:ік|iк)\s+баж\w*)"
_MONEY_SUM = r"(?P<amount>\d[\d\s ]*(?:[.,]\d{1,2})?\s*(?:тенге|теңге|тг\b|₸))"
# «пошлина в размере 360 000 тенге», «пошлина — 360 000 тенге», «пошлина на 360 000 тенге».
_STATE_DUTY_AMOUNT_AFTER_RE = re.compile(
    rf"{_STATE_DUTY_CUE}\s*"
    r"(?:(?:в\s+размере|в\s+сумме|на\s+сумму|составля\w*|уплачен\w*|оплачен\w*|равн\w*|"
    r"мөлшерінде|сомасында|на)\s*)?"
    rf"[\s:—–\-]{{0,4}}{_MONEY_SUM}",
    re.IGNORECASE,
)
# «уплачено 360 000 тенге государственной пошлины».
_STATE_DUTY_AMOUNT_BEFORE_RE = re.compile(
    rf"{_MONEY_SUM}\s*(?:в\s+счёт\s+|в\s+счет\s+)?{_STATE_DUTY_CUE}",
    re.IGNORECASE,
)

_PAID_IN_FULL_RE = re.compile(
    r"(?:оплат\w*|уплат\w*|внес\w*)[^\n]{0,90}(?:полностью|в\s+полном\s+объ[её]ме|всю\s+сумм\w*)|"
    r"(?:полностью|в\s+полном\s+объ[её]ме)[^\n]{0,70}(?:оплат\w*|уплат\w*)|"
    r"(?:толық|толығымен)[^\n]{0,70}(?:төлед\w*|төлен\w*)|(?:төлед\w*|төлен\w*)[^\n]{0,70}(?:толық|толығымен)",
    re.IGNORECASE,
)
_COUNTERPARTY_NONPERFORMANCE_RE = re.compile(
    r"(?:ответчик|исполнитель|подрядчик|продавец|изготовитель|жауапкер|орындаушы|мердігер|сатушы)"
    r"[^\n]{0,140}(?:не\s+исполнил|не\s+выполнил|не\s+изготовил|не\s+установил|не\s+передал|просроч\w*|"
    r"орындама\w*|жасама\w*|орнатпа\w*|берме\w*|кешіктір\w*|мерзім\w*\s+бұз\w*)",
    re.IGNORECASE,
)
_BUYER_NONPAYMENT_BASIS_RE = re.compile(
    r"неоплат\w*\s+покупател\w*|"
    r"неисполнени\w*\s+покупател\w*[^\n]{0,140}предварительн\w*\s+оплат\w*|"
    r"покупател\w*[^\n]{0,140}не\s+исполн\w*[^\n]{0,90}предварительн\w*\s+оплат\w*|"
    r"сатып\s+алушы[^\n]{0,140}(?:төлеме\w*|алдын\s+ала\s+төлем\w*[^\n]{0,80}(?:орындама\w*|төлеме\w*))",
    re.IGNORECASE,
)
_WORKS_CONTEXT_RE = re.compile(
    r"работ\w*|услуг\w*|подряд\w*|ремонт\w*|монтаж\w*|изготовлен\w*|установк\w*|установил\w*|"
    r"жұмыс\w*|қызмет\w*|мердігер\w*|жөндеу\w*|монтаж\w*|дайында\w*|орнат\w*",
    re.IGNORECASE,
)
_WORK_DELAY_RE = re.compile(
    r"срок\w*[^\n]{0,120}(?:работ\w*|услуг\w*|изготовлен\w*|установк\w*)|"
    r"(?:работ\w*|услуг\w*|изготовлен\w*|установк\w*)[^\n]{0,120}(?:срок\w*|просроч\w*)|"
    r"мерзім\w*[^\n]{0,120}(?:жұмыс\w*|қызмет\w*|дайында\w*|орнат\w*)|"
    r"(?:жұмыс\w*|қызмет\w*|дайында\w*|орнат\w*)[^\n]{0,120}(?:мерзім\w*|кешіктір\w*)",
    re.IGNORECASE,
)
_GOODS_RETURN_PENALTY_BASIS_RE = re.compile(
    r"(?:обмен\w*|возврат\w*)[^\n]{0,140}товар\w*|"
    r"товар\w*[^\n]{0,180}(?:ненадлежащ\w*\s+качеств\w*|надлежащ\w*\s+качеств\w*)|"
    r"(?:айырбастау\w*|қайтар\w*)[^\n]{0,140}тауар\w*|"
    r"тауар\w*[^\n]{0,180}(?:сапасыз\w*|тиісті\s+сапа\w*)",
    re.IGNORECASE,
)
_WORK_DELAY_PENALTY_BASIS_RE = re.compile(
    r"нарушен\w*\s+срок\w*[^\n]{0,160}(?:начал\w*|окончан\w*|выполнени\w*)[^\n]{0,120}(?:работ\w*|услуг\w*)|"
    r"(?:работ\w*|услуг\w*)[^\n]{0,180}неустойк\w*[^\n]{0,120}(?:кажд\w*\s+день|просроч\w*)|"
    r"мерзім\w*[^\n]{0,160}(?:бастал\w*|аяқтал\w*|орында\w*)[^\n]{0,120}(?:жұмыс\w*|қызмет\w*)|"
    r"(?:жұмыс\w*|қызмет\w*)[^\n]{0,180}(?:тұрақсыздық\s+айыб\w*|өсімпұл\w*)[^\n]{0,120}(?:әр\s+күн|кешіктір\w*)",
    re.IGNORECASE,
)


def _text(values: list[str]) -> str:
    """Join non-empty draft lines for deterministic matching."""
    return "\n".join(str(value) for value in values or [] if str(value).strip())


def _positive_term_in_segment(segment: str, term_re: Pattern[str]) -> bool:
    """Return True when at least one remedy term is not explicitly excluded."""
    for term in term_re.finditer(segment):
        before_start = max(0, term.start() - 70)
        prior_intents = list(_INTENT_VERB_RE.finditer(segment, 0, term.start()))
        if prior_intents:
            before_start = max(before_start, prior_intents[-1].end())
        before = segment[before_start:term.start()]
        after = segment[term.end():min(len(segment), term.end() + 50)]
        term_text = term.group(0).lower()
        if _TERM_EXCLUSION_BEFORE_RE.search(before):
            continue
        if _TERM_EXCLUSION_AFTER_RE.search(after):
            continue
        if term_text.endswith(("сыз", "сіз")):
            continue
        return True
    return False


def _explicit_intent(text: str, term_re: Pattern[str]) -> bool:
    """Match a positive request inside its sentence while allowing multiline lists."""
    value = text or ""
    for verb in _INTENT_VERB_RE.finditer(value):
        prefix = value[max(0, verb.start() - 16):verb.start()]
        if _NEGATION_BEFORE_RE.search(prefix):
            continue

        previous_boundaries = [value.rfind(mark, 0, verb.start()) for mark in ".?!"]
        sentence_start = max(previous_boundaries) + 1
        sentence_start = max(sentence_start, verb.start() - 100)

        next_boundaries = [value.find(mark, verb.end()) for mark in ".?!"]
        next_boundaries = [position for position in next_boundaries if position >= 0]
        sentence_end = min(next_boundaries) if next_boundaries else len(value)
        sentence_end = min(sentence_end, verb.end() + 260)

        if _positive_term_in_segment(value[sentence_start:sentence_end], term_re):
            return True
    return False


def _explicit_penalty_amount(text: str) -> bool:
    """Найдена ли в тексте сумма, заявленная ИМЕННО как размер неустойки.

    Раньше слово и сумма должны были стоять в 16 символах друг от друга. Это
    пропускало черновое «неустойку 112 000 тенге» и резало профессиональное
    «неустойку за нарушение срока сдачи работ в размере 112 000 (сто двенадцать
    тысяч) тенге» — гейт наказывал за качество формулировки.

    Зазор расширен, но не безоговорочно: «неустойку, исходя из суммы договора
    1 200 000 тенге» по-прежнему НЕ считается указанием размера, потому что
    названа база начисления, а не присуждаемая сумма.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        for word in _PENALTY_WORD_RE.finditer(sentence):
            for amount in _PENALTY_SUM_RE.finditer(sentence):
                if amount.start() >= word.end():
                    gap = sentence[word.end():amount.start()]
                else:
                    gap = sentence[amount.end():word.start()]
                    if amount.end() > word.start():
                        continue
                if len(gap) > 140:
                    continue
                if _BASE_CUE_RE.search(gap):
                    continue
                if len(gap) <= 16 or _AWARD_CUE_RE.search(gap):
                    return True
    return False


def _has_complete_penalty_calculation(text: str) -> bool:
    """Accept only an explicit penalty amount or a rate + money base + period."""
    value = text or ""
    if _explicit_penalty_amount(value):
        return True
    return bool(_RATE_RE.search(value) and _AMOUNT_RE.search(value) and _PERIOD_RE.search(value))


def _penalty_request_without_amount(requests: list[str]) -> bool:
    """Require each penalty demand to carry its own amount or complete calculation."""
    for request in requests or []:
        text = str(request)
        if _PENALTY_REQUEST_RE.search(text) and not _has_complete_penalty_calculation(text):
            return True
    return False


def _penalty_amounts(lines: list[str] | None) -> set[int]:
    """Amounts stated on penalty lines, parsed by the canonical fail-closed parser.

    ``parse_all_amounts_kzt`` is the single money parser of the product: it
    rejects malformed grouping such as ``12 34 567 тенге`` instead of silently
    reading a suffix. Reconciliation must never be satisfied by a number the
    claim-price and state-duty paths would refuse to read.
    """
    amounts: set[int] = set()
    for line in lines or []:
        text = str(line)
        if _PENALTY_REQUEST_RE.search(text):
            amounts.update(parse_all_amounts_kzt(text))
    return amounts


def _calculation_relief_errors(draft: ClaimDraft) -> list[str]:
    """Reconcile each calculated monetary component with the court prayer.

    A total alone is not enough: principal and penalty have different legal bases
    and must survive as separately identifiable components on both sides.  The
    structured calculation is optional for legacy/non-monetary drafts, but once it
    is present it is authoritative and must agree with ``ПРОШУ СУД``.
    """
    calculation = _text(draft.calculation)
    requests = _text(draft.requests)
    if not calculation:
        return []

    errors: list[str] = []
    calculation_has_penalty = bool(_PENALTY_REQUEST_RE.search(calculation))
    prayer_has_penalty = bool(_PENALTY_REQUEST_RE.search(requests))
    if calculation_has_penalty and not prayer_has_penalty:
        errors.append(
            "В структурированном расчёте есть неустойка/пеня, но соответствующий денежный компонент отсутствует в разделе «ПРОШУ СУД»."
        )
    elif prayer_has_penalty and not calculation_has_penalty:
        errors.append(
            "В разделе «ПРОШУ СУД» заявлена неустойка/пеня, но этот денежный компонент отсутствует в структурированном расчёте."
        )
    elif calculation_has_penalty and prayer_has_penalty:
        calculation_amounts = _penalty_amounts(draft.calculation)
        prayer_amounts = _penalty_amounts(draft.requests)
        if calculation_amounts and prayer_amounts and calculation_amounts.isdisjoint(prayer_amounts):
            calculated = ", ".join(f"{value:,}".replace(",", " ") for value in sorted(calculation_amounts))
            prayed = ", ".join(f"{value:,}".replace(",", " ") for value in sorted(prayer_amounts))
            errors.append(
                "Размер неустойки в структурированном расчёте "
                f"({calculated} тенге) не совпадает с размером в разделе «ПРОШУ СУД» ({prayed} тенге)."
            )
    return errors


def _grouped(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _state_duty_amounts(lines: list[str]) -> set[int]:
    """Суммы, названные в тексте именно размером государственной пошлины.

    Привязка узкая и с обеих сторон от слова «пошлина»: «пошлина 120 000 тенге»
    и «уплачено 120 000 тенге государственной пошлины». Соседняя сумма расходов
    на представителя в том же предложении размером пошлины не считается —
    ложная блокировка здесь так же вредна, как пропуск.
    """
    amounts: set[int] = set()
    for line in lines or []:
        text = str(line)
        for pattern in (_STATE_DUTY_AMOUNT_AFTER_RE, _STATE_DUTY_AMOUNT_BEFORE_RE):
            for match in pattern.finditer(text):
                value = parse_amount_kzt(match.group("amount"))
                if value is not None:
                    amounts.add(value)
    return amounts


def _state_duty_errors(draft: ClaimDraft) -> list[str]:
    """Детерминированный размер пошлины сильнее любого числа, написанного моделью.

    Пошлину считает korgan.legal_calc по цене иска и статусу истца. Если иск
    где-то называет другую сумму — в фактах, приложениях, расчёте или просительной
    части — документ противоречит сам себе, а суд вернёт его как оплаченный не
    полностью. Расхождение не «сглаживается»: оно блокирует filing-ready.
    """
    deterministic = parse_amount_kzt(draft.state_duty or "")
    if deterministic is None:
        return []

    stated = _state_duty_amounts([
        *(draft.facts or []),
        *(draft.attachments or []),
        *(draft.requests or []),
        *(draft.calculation or []),
        *(draft.legal_basis or []),
    ])
    conflicting = sorted(value for value in stated if value != deterministic)
    if not conflicting:
        return []

    listed = ", ".join(_grouped(value) for value in conflicting)
    return [
        f"Размер государственной пошлины в тексте иска ({listed} тенге) не совпадает с детерминированным "
        f"расчётом ({_grouped(deterministic)} тенге). "
        "Действителен детерминированный расчёт: приведите текст иска в соответствие с ним."
    ]


def _consumer_qualification_errors(case_context: str, draft: ClaimDraft) -> list[str]:
    """Иск не вправе опираться на статус потребителя, пока цель не установлена.

    Подтверждённая статья ЗПП подтверждает текст нормы, но не то, что истец под
    неё подпадает: потребитель — это физическое лицо, приобретающее для личных,
    семейных, домашних нужд вне предпринимательской деятельности. Если цель в
    материалах не названа или названа предпринимательской, потребительская
    квалификация — выдуманный факт, а построенные на ней подсудность, отсрочка
    пошлины и специальные санкции разваливаются в суде.
    """
    if not asserts_consumer_law(draft):
        return []

    status = consumer_status(case_context, draft)
    if status is ConsumerStatus.ESTABLISHED:
        return []

    if status is ConsumerStatus.EXCLUDED:
        return [
            "Иск опирается на законодательство о защите прав потребителей, хотя по материалам дела истец "
            "под эту квалификацию не подпадает (истец не является физическим лицом либо приобретение связано "
            "с предпринимательской деятельностью). Исключите потребительское обоснование и постройте требование "
            "на нормах, применимых к установленным отношениям."
        ]

    return [
        "Иск опирается на законодательство о защите прав потребителей, но цель приобретения товара (работы, услуги) "
        "в материалах дела не установлена. Статус потребителя — факт, а не ссылка на закон: до filing-ready в фактах "
        "должно быть указано приобретение для личных, семейных, домашних нужд, не связанных с предпринимательской "
        "деятельностью, либо потребительское обоснование должно быть исключено."
    ]


def claim_consistency_errors(case_context: str, draft: ClaimDraft) -> list[str]:
    """Return deterministic claim contradictions that must survive model repair."""
    context = case_context or ""
    requests = _text(draft.requests)
    legal_basis = _text(draft.legal_basis)
    facts = _text(draft.facts)
    factual_record = f"{context}\n{facts}"

    errors: list[str] = []

    penalty_requested = _explicit_intent(context, _PENALTY_REQUEST_RE)
    costs_requested = _explicit_intent(context, _COST_REQUEST_RE)
    penalty_in_prayer = bool(_PENALTY_REQUEST_RE.search(requests))
    costs_in_prayer = bool(_COST_REQUEST_RE.search(requests))

    if penalty_requested and not penalty_in_prayer:
        errors.append(
            "Пользователь прямо просил взыскать неустойку/пеню, но это требование исчезло из раздела «ПРОШУ СУД». "
            "Нельзя молча терять заявленный способ защиты: включите исполнимое требование по VERIFIED-норме и расчету либо явно оставьте документ preliminary с указанием, каких данных не хватает."
        )

    if costs_requested and not costs_in_prayer:
        errors.append(
            "Пользователь прямо просил взыскать судебные расходы, но соответствующего требования нет в разделе «ПРОШУ СУД». "
            "Добавьте процессуально корректное требование о судебных расходах либо явно объясните, почему оно не может быть заявлено по текущим материалам."
        )

    if penalty_in_prayer and _penalty_request_without_amount(list(draft.requests or [])):
        errors.append(
            "В разделе «ПРОШУ СУД» заявлена денежная неустойка/пеня без конкретного размера или полного проверяемого расчета. "
            "До статуса filing-ready должны быть указаны размер неустойки либо ставка, денежная база и период расчета; иначе документ должен остаться preliminary."
        )

    if (
        _PAID_IN_FULL_RE.search(factual_record)
        and _COUNTERPARTY_NONPERFORMANCE_RE.search(factual_record)
        and _BUYER_NONPAYMENT_BASIS_RE.search(legal_basis)
    ):
        errors.append(
            "Правовое обоснование использует норму о неисполнении покупателем обязанности по предварительной оплате, "
            "хотя по материалам истец оплатил полностью, а нарушение допущено ответчиком. Такая норма направлена против другой фактической ситуации и должна быть исключена или заменена только на VERIFIED-норму, поддерживающую требование истца."
        )

    works_delay_case = bool(_WORKS_CONTEXT_RE.search(factual_record) and _WORK_DELAY_RE.search(factual_record))
    penalty_relevant = penalty_requested or penalty_in_prayer
    if (
        works_delay_case
        and penalty_relevant
        and _GOODS_RETURN_PENALTY_BASIS_RE.search(legal_basis)
        and not _WORK_DELAY_PENALTY_BASIS_RE.search(legal_basis)
    ):
        errors.append(
            "Неустойка по спору о просрочке выполнения работы/услуги обоснована нормой о возврате/качестве товара. "
            "Для filing-ready проекта требуется VERIFIED-норма именно о нарушении сроков начала/окончания выполнения работы (услуги) и соответствующий расчет."
        )

    errors.extend(_calculation_relief_errors(draft))
    errors.extend(_state_duty_errors(draft))
    errors.extend(_consumer_qualification_errors(context, draft))
    amount_errors = check_amount_consistency(draft)
    errors.extend(f"AMOUNT_MISMATCH: {item}" for item in amount_errors)
    return list(dict.fromkeys(errors))


def install_claim_consistency_guard() -> None:
    """Extend the existing senior preflight without replacing its protections."""
    current = senior_claim_preflight.deterministic_claim_preflight
    if getattr(current, "_korgan_claim_consistency_guard", False):
        return

    def guarded(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
        """Preserve original preflight errors and append consistency defects."""
        base = current(case_context, research, draft)
        extra = claim_consistency_errors(case_context, draft)
        return list(dict.fromkeys([*base, *extra]))

    guarded._korgan_claim_consistency_guard = True  # type: ignore[attr-defined]
    senior_claim_preflight.deterministic_claim_preflight = guarded
