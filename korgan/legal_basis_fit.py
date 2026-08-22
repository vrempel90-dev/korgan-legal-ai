"""Доказывает ли норма именно то требование, которое заявлено в иске.

Проверка цитаты и проверка выбора нормы — разные вещи, и KORGAN умел только
первую. На деле о взыскании 2 300 000 тенге предоплаты за невыполненный ремонт
раздел «Правовое обоснование» состоял из нормы о приёмке результата работ:
статья реальная, содержание процитировано корректно, дефектов у
:mod:`korgan.citation_audit` нет. Но приёмка — обязанность ЗАКАЗЧИКА осмотреть и
принять работу; она ничего не говорит о праве требовать деньги назад с
подрядчика. Документ ссылался на соседнюю главу кодекса вместо основания иска.

Отсюда правило этого модуля: норма подбирается от требования, а не от темы.
Сначала определяется, что именно взыскивается и почему (просительная часть —
единственный источник истины об этом), затем каждая норма в обосновании
относится к правовому институту, и институт сверяется с требованием:

* возврат предоплаты за невыполненные работы обосновывают отказ от договора с
  возвратом аванса при существенном нарушении подрядчиком, ответственность
  подрядчика за неисполнение либо неосновательное обогащение, если договор
  прекращён;
* норма о приёмке результата работ обосновать его не может — это процедурная
  норма об обязанностях заказчика, то есть об обратном.

Когда ни одна норма в документе требование не поддерживает, модуль не
подставляет «похожую» и не молчит: документ получает видимую пометку о том, что
точную норму должен подобрать юрист. Явное «здесь нужен юрист» честнее
формально релевантной, но по существу нерабочей ссылки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.legal_types import ClaimDraft

LAWYER_PICK_MARKER = (
    "[ТРЕБУЕТ УТОЧНЕНИЯ: правовое основание требования — требуется подбор точной нормы "
    "юристом; приведённые нормы не обосновывают заявленное требование]"
)

NOTE_PREFIX = "Требуется подбор точной нормы юристом: "


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


# ─── Правовые институты, к которым относится абзац обоснования ────────────────

_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        # Обязанность заказчика осмотреть и принять результат. Процедурная норма
        # о действиях ЗАКАЗЧИКА — она не даёт права требовать деньги обратно.
        "work_acceptance",
        (
            r"\bприемк\w*\b|\bприёмк\w*\b",
            r"\bприня\w*\s+(?:результат|выполненн\w*\s+работ|работ)\w*",
            r"\bосмотрет\w*\b.{0,60}\bприня\w*",
            r"\bуклон\w*\b.{0,40}\bприемк|\bуклон\w*\b.{0,40}\bприёмк",
            r"\bакт\w*\s+(?:выполненн\w*\s+работ|приемк|приёмк)\w*",
        ),
    ),
    (
        "contract_withdrawal",
        (
            r"\bотказ\w*\b.{0,60}\b(?:от\s+)?(?:исполнени\w*\s+)?договор\w*",
            r"\bрасторж\w*\b.{0,60}\bдоговор\w*",
            r"\bсущественн\w*\s+наруш\w*",
            r"\b(?:возврат\w*|вернут\w*|взыска\w*)\b.{0,60}\b(?:аванс\w*|предоплат\w*|задатк\w*"
            r"|предварительн\w*\s+оплат\w*)",
            r"\bодносторонн\w*\s+отказ\w*",
        ),
    ),
    (
        "contractor_liability",
        (
            r"\bответственност\w*\b.{0,60}\bподрядчик\w*",
            r"\bподрядчик\w*\b.{0,80}\b(?:не\s+выполн|не\s+присту|наруш|просроч)\w*",
            r"\bнаруш\w*\b.{0,60}\bсрок\w*\b.{0,60}\bработ\w*",
            r"\bпросрочк\w*\b.{0,60}\b(?:выполнени|работ|исполнени)\w*",
            r"\bнеисполнени\w*\b.{0,60}\bобязательств\w*",
            r"\bненадлежащ\w*\s+исполнени\w*",
        ),
    ),
    (
        "unjust_enrichment",
        (
            r"\bнеосновательн\w*\b.{0,40}\b(?:обогащ|приобрет|сбереж)\w*",
            r"\bбез\s+установленн\w*\s+закон\w*\b.{0,40}\bоснован\w*",
            r"\bотпал\w*\s+основани\w*|\bосновани\w*\s+отпал\w*",
        ),
    ),
    (
        "loan_repayment",
        (
            r"\bза[её]м\w*\b|\bзайм\w*\b",
            r"\bза[её]мщик\w*\b.{0,60}\bвозврат\w*",
        ),
    ),
    (
        "damages",
        (r"\bубытк\w*\b", r"\bвозмещени\w*\b.{0,40}\bвред\w*", r"\bреальн\w*\s+ущерб\w*"),
    ),
    (
        "penalty",
        (r"\bнеустойк\w*\b", r"\bпен[яию]\b", r"\bштраф\w*\b"),
    ),
    (
        "procedure",
        (
            r"\bподсудност\w*\b",
            r"\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*",
            r"\bформ\w*\s+и\s+содержани\w*\s+иск\w*",
            r"\bгпк\s*рк\b",
        ),
    ),
)


def categorize_provision(line: str) -> set[str]:
    """Правовые институты, к которым относится один абзац обоснования."""
    text = str(line or "")
    return {code for code, patterns in _CATEGORY_PATTERNS if _has(text, *patterns)}


# ─── Требования и нормы, которые их действительно обосновывают ────────────────


@dataclass(frozen=True, slots=True)
class ReliefKind:
    """Заявленное требование и институты, способные его обосновать."""

    code: str
    label: str
    supporting: frozenset[str]
    irrelevant: frozenset[str]
    guidance: str


PREPAYMENT_REFUND_WORKS = ReliefKind(
    code="prepayment_refund_works",
    label="взыскание предоплаты (аванса) за невыполненные работы",
    supporting=frozenset({"contract_withdrawal", "contractor_liability", "unjust_enrichment"}),
    irrelevant=frozenset({"work_acceptance"}),
    guidance=(
        "требование обосновывают право заказчика отказаться от договора и потребовать "
        "возврата аванса при существенном нарушении подрядчиком (нормы ГК РК о подряде — "
        "об ответственности подрядчика и правах заказчика, не о приёмке) либо нормы ГК РК "
        "о неосновательном обогащении, если договор считается прекращённым"
    ),
)

PREPAYMENT_REFUND_GOODS = ReliefKind(
    code="prepayment_refund_goods",
    label="взыскание предоплаты за непоставленный товар",
    supporting=frozenset({"contract_withdrawal", "unjust_enrichment", "damages"}),
    irrelevant=frozenset({"work_acceptance"}),
    guidance=(
        "требование обосновывают право покупателя отказаться от договора и потребовать "
        "возврата предварительной оплаты при непередаче товара либо нормы ГК РК "
        "о неосновательном обогащении"
    ),
)

DEBT_RECOVERY_LOAN = ReliefKind(
    code="debt_recovery_loan",
    label="взыскание долга по займу",
    supporting=frozenset({"loan_repayment", "unjust_enrichment", "contract_withdrawal"}),
    irrelevant=frozenset({"work_acceptance"}),
    guidance=(
        "требование обосновывают нормы ГК РК о займе — обязанность заёмщика возвратить "
        "полученную сумму в согласованный срок"
    ),
)

DAMAGES_RECOVERY = ReliefKind(
    code="damages_recovery",
    label="возмещение убытков (вреда)",
    supporting=frozenset({"damages", "contractor_liability", "unjust_enrichment"}),
    irrelevant=frozenset({"work_acceptance"}),
    guidance=(
        "требование обосновывают нормы ГК РК об ответственности за нарушение обязательства "
        "либо о возмещении причинённого вреда — с составом ответственности и причинной связью"
    ),
)


def detect_relief(requests: list[str], context_lines: list[str] | None = None) -> ReliefKind | None:
    """Определить требование по просительной части, затем — по фактам.

    Просительная часть решает: именно её должно доказывать обоснование. Факты
    используются только чтобы уточнить предмет («предоплата за ремонт»), когда
    просительная часть говорит просто «взыскать сумму».
    """
    prayer = " ".join(str(item) for item in requests or [])
    background = " ".join(str(item) for item in context_lines or [])
    both = f"{prayer}\n{background}"

    money_claim = _has(prayer, r"\bвзыска\w*\b", r"\bвернут\w*\b|\bвозврат\w*\b")
    if not money_claim:
        return None

    # «Предварительная оплата» — та же предоплата, и именно так её называет
    # и договор, и просительная часть. Пропустив эту форму, проверка нормы
    # молча выключалась ровно на тех делах, ради которых написана.
    prepayment = _has(
        both,
        r"\bпредоплат\w*\b",
        r"\bаванс\w*\b",
        r"\bзадатк\w*\b",
        r"\bпредварительн\w*\s+(?:оплат\w*|платеж\w*)\b",
    )
    works = _has(
        both,
        r"\bработ\w*\b", r"\bподряд\w*\b", r"\bремонт\w*\b", r"\bстроительн\w*\b", r"\bмонтаж\w*\b",
    )
    goods = _has(both, r"\bтовар\w*\b", r"\bпоставк\w*\b", r"\bпоставщик\w*\b")
    loan = _has(both, r"\bза[её]м\w*\b", r"\bзайм\w*\b", r"\bрасписк\w*\b", r"\bв\s+долг\b")

    if prepayment and works:
        return PREPAYMENT_REFUND_WORKS
    if prepayment and goods:
        return PREPAYMENT_REFUND_GOODS
    if loan:
        return DEBT_RECOVERY_LOAN
    if _has(prayer, r"\bубытк\w*\b", r"\bущерб\w*\b", r"\bвред\w*\b"):
        return DAMAGES_RECOVERY
    return None


def _sentence(text: str) -> str:
    """Заглавная только у первой буквы: `str.capitalize` гасит «ГК РК» в «гк рк»."""
    return text[:1].upper() + text[1:] if text else text


def legal_basis_defects(
    *,
    requests: list[str],
    legal_basis: list[str],
    context_lines: list[str] | None = None,
) -> list[str]:
    """Замечания о несоответствии обоснования заявленному требованию."""
    relief = detect_relief(requests, context_lines)
    if relief is None:
        return []

    categories: set[str] = set()
    for line in legal_basis or []:
        categories |= categorize_provision(line)

    if categories & relief.supporting:
        return []

    misleading = sorted(categories & relief.irrelevant)
    if misleading:
        return [
            f"{NOTE_PREFIX}требование — {relief.label}, но правовое обоснование опирается "
            "на норму о приёмке результата работ, то есть на обязанность заказчика, "
            f"а не на основание взыскания. {_sentence(relief.guidance)}."
        ]

    if not [line for line in legal_basis or [] if str(line).strip()]:
        return [
            f"{NOTE_PREFIX}требование — {relief.label}, но правовое обоснование в проекте "
            f"отсутствует. {_sentence(relief.guidance)}."
        ]

    return [
        f"{NOTE_PREFIX}требование — {relief.label}, но ни одна норма в правовом обосновании "
        f"его прямо не поддерживает. {_sentence(relief.guidance)}."
    ]


def enforce_legal_basis_fit(draft: ClaimDraft) -> list[str]:
    """Пометить документ, если норма не доказывает заявленное требование.

    Нерелевантный абзац не удаляется молча — он остаётся, но перестаёт быть
    единственным правовым обоснованием: рядом появляется видимая пометка о том,
    что точную норму должен подобрать юрист. Подстановка «похожей» нормы вместо
    этого и есть дефект, который модуль ловит.
    """
    defects = legal_basis_defects(
        requests=list(draft.requests or []),
        legal_basis=list(draft.legal_basis or []),
        context_lines=[draft.title, *(draft.facts or [])],
    )
    if not defects:
        return []

    if LAWYER_PICK_MARKER not in draft.legal_basis:
        draft.legal_basis.append(LAWYER_PICK_MARKER)

    # Первым в чек-листе: замечание о том, что документ не доказывает
    # собственное требование, важнее любого пробела в реквизитах, а хвост
    # длинного чек-листа обрезается лимитом Telegram.
    for defect in reversed(defects):
        if defect not in draft.verification_notes:
            draft.verification_notes.insert(0, defect)

    return defects
