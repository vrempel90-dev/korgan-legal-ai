"""Обязательные положения по типам документов — защита от тихих регрессий.

A clause that was present in v3 and gone in v4 is invisible to every check that
looks at the document in isolation: the v4 document is internally consistent,
well formed, and simply poorer. Пункт 7.4 об обработке персональных данных
исчез exactly that way.

So the required content of each document type is pinned here, next to the code
that produces it, and asserted on regeneration. A regeneration that dropped a
pinned clause fails instead of shipping.

The specs describe *presence of substance*, not wording: each requirement is a
set of alternative patterns, so a rephrased clause still passes while a deleted
one does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RequiredClause:
    """One pinned obligation of a document type."""

    label: str
    patterns: tuple[str, ...]
    rationale: str = ""

    def is_present(self, text: str) -> bool:
        return any(re.search(pattern, text) for pattern in self.patterns)


@dataclass(frozen=True, slots=True)
class GoldenSpec:
    document_type: str
    title: str
    required: tuple[RequiredClause, ...] = field(default_factory=tuple)

    def missing(self, text: str) -> list[str]:
        normalized = (text or "").replace("ё", "е").replace("Ё", "Е").lower()
        return [clause.label for clause in self.required if not clause.is_present(normalized)]


# Requirements shared by every contract regardless of its kind.
_CONTRACT_BASELINE: tuple[RequiredClause, ...] = (
    RequiredClause(
        "преамбула с идентификацией сторон и основанием полномочий",
        (r"в дальнейшем.{0,400}на основании",),
        "final-legal-qa.md, Release Gate, проверка 4",
    ),
    RequiredClause("предмет договора", (r"предмет",)),
    RequiredClause("права и обязанности сторон", (r"обяз(?:ан|уется|анност)",)),
    RequiredClause("ответственность сторон", (r"ответственност",)),
    RequiredClause("срок действия и прекращение", (r"срок действия|расторжен|прекращен",)),
    RequiredClause("разрешение споров", (r"спор",)),
    RequiredClause("реквизиты и подписи сторон", (r"реквизиты",)),
)

_PERSONAL_DATA = RequiredClause(
    "обработка персональных данных пользователей",
    (r"персональн\w* данн",),
    "предмет связан с обработкой пользовательских сообщений; пункт терялся между версиями",
)

_IP_RIGHTS = RequiredClause(
    "права на результат работ (интеллектуальная собственность)",
    (r"исключительн\w* прав|интеллектуальн\w* собственност|прав\w* на результат",),
)

_CONFIDENTIALITY = RequiredClause(
    "конфиденциальность",
    (r"конфиденциальн",),
)


SPECS: dict[str, GoldenSpec] = {
    "claim": GoldenSpec(
        "claim",
        "Исковое заявление",
        (
            RequiredClause("наименование суда", (r"в суд:",)),
            RequiredClause("данные истца", (r"истец:",)),
            RequiredClause("данные ответчика", (r"ответчик:",)),
            RequiredClause("цена иска", (r"цена иска",)),
            RequiredClause("государственная пошлина", (r"госпошлина|государственн\w* пошлин",)),
            RequiredClause("правовое обоснование", (r"правовое обоснование",)),
            RequiredClause("просительная часть", (r"прошу суд",)),
            RequiredClause("приложения", (r"приложения",)),
        ),
    ),
    "response": GoldenSpec(
        "response",
        "Отзыв на исковое заявление",
        (
            RequiredClause("наименование суда", (r"в суд:",)),
            RequiredClause("ссылка на дело", (r"дело №",)),
            RequiredClause("данные истца", (r"истец:",)),
            RequiredClause("данные ответчика", (r"ответчик:",)),
            RequiredClause("фактические обстоятельства", (r"фактические обстоятельства",)),
            RequiredClause("возражения по существу", (r"возражения по существу",)),
            RequiredClause("правовое обоснование", (r"правовое обоснование",)),
            RequiredClause("процессуальные требования", (r"прошу суд",)),
            RequiredClause("приложения", (r"приложения",)),
        ),
    ),
    "contract_services": GoldenSpec(
        "contract_services",
        "Договор возмездного оказания услуг",
        _CONTRACT_BASELINE
        + (
            RequiredClause("порядок приёмки услуг", (r"приемк|акт оказанных услуг",)),
            RequiredClause("цена и порядок расчётов", (r"цена|оплат|расчет",)),
        ),
    ),
    "contract_it_services": GoldenSpec(
        "contract_it_services",
        "Договор на разработку и сопровождение IT-решения",
        _CONTRACT_BASELINE
        + (
            RequiredClause("порядок приёмки работ", (r"приемк|акт выполненных работ",)),
            RequiredClause("цена и порядок расчётов", (r"цена|оплат|расчет",)),
            _IP_RIGHTS,
            _PERSONAL_DATA,
            _CONFIDENTIALITY,
            RequiredClause("гарантийные обязательства", (r"гарантийн|гаранти",)),
        ),
    ),
    "contract_supply": GoldenSpec(
        "contract_supply",
        "Договор поставки",
        _CONTRACT_BASELINE
        + (
            RequiredClause("наименование и количество товара", (r"товар",)),
            RequiredClause("срок и порядок поставки", (r"поставк",)),
            RequiredClause("качество товара", (r"качеств",)),
        ),
    ),
    "contract_work": GoldenSpec(
        "contract_work",
        "Договор подряда",
        _CONTRACT_BASELINE
        + (
            RequiredClause("результат работ", (r"результат работ|выполнен\w* работ",)),
            RequiredClause("сроки выполнения работ", (r"срок\w* выполнени|срок\w* работ",)),
            RequiredClause("порядок сдачи-приёмки", (r"приемк|сдач",)),
        ),
    ),
    "contract_lease": GoldenSpec(
        "contract_lease",
        "Договор имущественного найма (аренды)",
        _CONTRACT_BASELINE
        + (
            RequiredClause("объект найма", (r"объект|имуществ|помещен",)),
            RequiredClause("размер и порядок внесения платы", (r"плат",)),
            RequiredClause("передача и возврат имущества", (r"передач|возврат",)),
        ),
    ),
    "contract_loan": GoldenSpec(
        "contract_loan",
        "Договор займа",
        _CONTRACT_BASELINE
        + (
            RequiredClause("сумма займа", (r"сумм\w* займа|заем|займ",)),
            RequiredClause("срок и порядок возврата", (r"возврат",)),
            RequiredClause("вознаграждение или его отсутствие", (r"вознагражден|беспроцентн",)),
        ),
    ),
    "contract_sale": GoldenSpec(
        "contract_sale",
        "Договор купли-продажи",
        _CONTRACT_BASELINE
        + (
            RequiredClause("предмет купли-продажи", (r"товар|имуществ",)),
            RequiredClause("цена и порядок оплаты", (r"цена|оплат",)),
            RequiredClause("передача товара", (r"передач",)),
        ),
    ),
    "contract_employment": GoldenSpec(
        "contract_employment",
        "Трудовой договор",
        _CONTRACT_BASELINE
        + (
            RequiredClause("трудовая функция и место работы", (r"трудов\w* функци|место работы|должност",)),
            RequiredClause("режим рабочего времени и отдыха", (r"рабоч\w* врем|отдых",)),
            RequiredClause("оплата труда", (r"оплат\w* труда|заработн\w* плат",)),
            RequiredClause("охрана труда", (r"охран\w* труда|безопасн",)),
        ),
    ),
}


def missing_required_clauses(document_type: str, text: str) -> list[str]:
    """Return pinned clauses that a regenerated document no longer contains."""
    spec = SPECS.get(document_type)
    if spec is None:
        raise KeyError(f"нет golden-спецификации для типа документа: {document_type}")
    return spec.missing(text)


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """A pinned example plus the date its legal citations were last reconciled."""

    document_type: str
    cited_acts: tuple[str, ...]
    citations_checked_on: str
    note: str = ""

    @property
    def cites_law(self) -> bool:
        return bool(self.cited_acts)

    @property
    def citations_need_check(self) -> bool:
        return self.cites_law and not self.citations_checked_on


def golden_cases() -> list[GoldenCase]:
    """Read the golden case registry (data, refreshed independently of code)."""
    import json
    from pathlib import Path

    path = Path(__file__).with_name("data") / "golden_cases.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        GoldenCase(
            document_type=str(item["document_type"]),
            cited_acts=tuple(str(x) for x in item.get("cited_acts", [])),
            citations_checked_on=str(item.get("citations_checked_on", "")),
            note=str(item.get("note", "")),
        )
        for item in raw.get("cases", [])
    ]
