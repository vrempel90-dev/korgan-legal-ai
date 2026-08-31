"""Подтверждены ли материалами дела заявленные судебные издержки.

Издержки — не правовое требование, а расход. У него нет своей нормы и своей
позиции: он либо понесён и подтверждён документом, либо его нет. Суд присуждает
только фактически понесённые и документально подтверждённые расходы на
представителя, экспертизу или оценку.

Разрыв выглядел так: иск просил взыскать 500 000 тенге расходов на оплату услуг
представителя, а в деле не было ни договора об оказании юридических услуг, ни
квитанции, ни платёжного поручения, ни единого факта о том, что представитель
вообще привлекался. Документ выпускался с оценкой 10.0. Клиент читал в нём
обещание денег, которых суд не присудит, а ответчик получал повод сказать, что
истец просит непонятно что.

Подтверждением здесь считается только названный в материалах документ об услуге
или о её оплате: договор об оказании услуг, квитанция, платёжное поручение, чек,
акт, расписка. Само требование подтверждением не является — «взыскать расходы на
представителя в размере 500 000 тенге» это ровно то утверждение, которое
проверяется. Чужой платёжный документ тоже не годится: платёжное поручение по
поставке ничего не говорит о юридических услугах, поэтому документ и расход
должны стоять в одном предложении.

Требование берётся только из просительной части самого документа. Отзыв на иск
разбирает чужие издержки постоянно — «требование о взыскании расходов на
представителя не подтверждено», — и если читать это как собственное требование
ответчика, блокируется ровно то возражение, ради которого документ написан.

Государственная пошлина сюда не входит: она считается детерминированно и живёт
в korgan/claim_state_duty.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+")


@dataclass(frozen=True, slots=True)
class ExpenseKind:
    """Издержка, которую взыскивают только по документу."""

    code: str
    label: str
    pattern: re.Pattern[str]
    guidance: str


EXPENSE_KINDS: tuple[ExpenseKind, ...] = (
    ExpenseKind(
        code="representative",
        label="расходы на представителя и юридическую помощь",
        pattern=re.compile(
            r"представител\w*|юридическ\w*\s+(?:услуг\w*|помощ\w*)|адвокат\w*|"
            r"өкіл\w*|заң\w*\s+көмег\w*",
            re.IGNORECASE,
        ),
        guidance=(
            "нужны договор об оказании юридических услуг и документ об оплате: "
            "суд присуждает только фактически понесённые и подтверждённые расходы"
        ),
    ),
    ExpenseKind(
        code="expert",
        label="расходы на экспертизу и оценку",
        pattern=re.compile(
            r"экспертиз\w*|эксперт\w*|оценк\w*\s+(?:стоимост\w*|имуществ\w*|ущерб\w*)|"
            r"оценщик\w*|сарапта\w*",
            re.IGNORECASE,
        ),
        guidance="нужны документ о назначении или проведении исследования и документ об его оплате",
    ),
)

# Расход заявлен ко взысканию: без этого слово «экспертиза» в фабуле остаётся
# обстоятельством дела, а не требованием о деньгах.
_EXPENSE_DEMAND_RE = re.compile(
    r"(?:взыска\w*|взыскани\w*|возмест\w*|возмещени\w*|отнести\s+на|"
    r"прош\w*\s+присуд\w*|өндір\w*)",
    re.IGNORECASE,
)

# Слово «расход»/«издержки» рядом с видом издержки: без него «взыскать с
# представителя ответчика» читалось бы как требование о расходах.
_EXPENSE_NOUN_RE = re.compile(
    r"расход\w*|издерж\w*|затрат\w*|услуг\w*|шығын\w*|шығыс\w*", re.IGNORECASE
)

# Документ, из которого расход виден: договор об услуге либо доказательство
# оплаты. Голое «оплачено» без документа сюда намеренно не входит — расход
# подтверждает бумага, а не утверждение о ней.
_PROOF_RE = re.compile(
    r"договор\w*\s+(?:об\s+оказани\w*|на\s+оказани\w*)|"
    r"квитанц\w*|платежн\w*\s+поручен\w*|платёжн\w*\s+поручен\w*|"
    r"кассов\w*\s+ордер\w*|\bчек\w*\b|фискальн\w*\s+чек\w*|"
    r"акт\w*\s+(?:выполненн\w*|оказанн\w*|приема\w*|при[её]м\w*)|"
    r"расписк\w*|сч[её]т[- ]фактур\w*|\bсч[её]т\w*\b|"
    r"түбіртек\w*|төлем\s+тапсырма\w*",
    re.IGNORECASE,
)

# Государственная пошлина считается детерминированно и проверяется отдельно.
_STATE_DUTY_RE = re.compile(r"пошлин\w*|мемлекеттік\s+баж", re.IGNORECASE)


def _sentences(lines: list[str] | None) -> list[str]:
    result: list[str] = []
    for line in lines or []:
        for part in _SENTENCE_SPLIT_RE.split(str(line or "")):
            if part.strip():
                result.append(part.strip())
    return result


def _is_demand(sentence: str) -> bool:
    return bool(_EXPENSE_DEMAND_RE.search(sentence) and _EXPENSE_NOUN_RE.search(sentence))


def _demanded(kind: ExpenseKind, sentences: list[str]) -> bool:
    return any(
        kind.pattern.search(sentence) and _is_demand(sentence) and not _STATE_DUTY_RE.search(sentence)
        for sentence in sentences
    )


def _supported(kind: ExpenseKind, sentences: list[str]) -> bool:
    """Документ и расход названы в одном предложении, и это не само требование."""
    return any(
        kind.pattern.search(sentence) and _PROOF_RE.search(sentence) and not _is_demand(sentence)
        for sentence in sentences
    )


def unsupported_expense_claims(
    demands: list[str] | None, materials: list[str] | None = None, case_context: str = ""
) -> list[str]:
    """Издержки, заявленные ко взысканию без подтверждающего документа.

    demands — просительная часть самого документа: только там документ требует
    деньги для себя. materials и case_context — всё остальное дело: факты,
    приложения, исходные материалы, где подтверждающий документ может быть
    назван.
    """
    demand_sentences = _sentences(demands)
    if not demand_sentences:
        return []
    proof_sentences = _sentences([*(demands or []), *(materials or []), case_context])

    findings: list[str] = []
    for kind in EXPENSE_KINDS:
        if not _demanded(kind, demand_sentences):
            continue
        if _supported(kind, proof_sentences):
            continue
        findings.append(
            f"заявлены {kind.label}, но материалы дела их не подтверждают: "
            f"ни договора об услуге, ни документа об оплате; {kind.guidance}"
        )
    return findings
