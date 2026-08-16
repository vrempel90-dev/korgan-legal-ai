"""Guard against paraphrasing a legal provision into something it does not say.

A verified article number is not enough: the point must also carry the
provision's own words so the paraphrase can be checked for mechanical drift.
Findings downgrade the point to NEEDS_VERIFICATION; they do not assert that the
legal conclusion is false.
"""

from __future__ import annotations

import re

_SCOPE_QUALIFIERS: tuple[tuple[str, str], ...] = (
    (r"представител", "норма ограничена случаем участия представителя"),
    (r"прокурор", "норма ограничена участием прокурора"),
    (r"несовершеннолетн", "норма ограничена несовершеннолетними"),
    (r"иностранн", "норма ограничена иностранным субъектом"),
    (r"\bтольк[оа]\b", "норма содержит ограничение «только»"),
    (r"исключительн", "норма содержит ограничение «исключительно»"),
    (r"при услови", "норма действует при определённом условии"),
    (r"в случа[еях]", "норма привязана к конкретному случаю"),
    (r"\bлибо\b", "норма предлагает альтернативу, а не единственный вариант"),
    (r"\bвправе\b", "норма формулирует право, а не обязанность"),
    (r"\bобяза[нно]", "норма формулирует обязанность, а не право"),
    (r"\bне\s+(?:вправе|допускается|может)\b", "норма содержит запрет"),
)

_SUBSTANTIVE_ANCHORS: tuple[tuple[str, str], ...] = (
    (r"доказательств", "доказательства"),
    (r"нормативн", "нормативные правовые акты"),
    (r"\bзакон", "закон"),
    (r"срок", "срок"),
    (r"пошлин", "государственная пошлина"),
    (r"подсудност", "подсудность"),
    (r"подведомственност", "подведомственность"),
    (r"неустойк", "неустойка"),
    (r"штраф", "штраф"),
    (r"процент", "проценты"),
    (r"убытк", "убытки"),
    (r"расторжен", "расторжение"),
    (r"письменн", "письменная форма"),
    (r"нотариальн", "нотариальная форма"),
    (r"возврат", "возврат"),
    (r"отказ", "отказ"),
)


def _normalize(text: str) -> str:
    return (text or "").replace("ё", "е").replace("Ё", "Е").lower()


def _present(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def paraphrase_defects(statement: str, provision_text: str) -> list[str]:
    claim = _normalize(statement)
    provision = _normalize(provision_text)

    if not claim.strip():
        return ["пустое юридическое утверждение"]
    if not quote_is_usable(provision_text):
        return [
            "нет пригодной дословной выдержки части/пункта нормы: пересказ невозможно сверить "
            "построчно, статус не может быть выше NEEDS_VERIFICATION"
        ]

    defects: list[str] = []
    for pattern, explanation in _SCOPE_QUALIFIERS:
        if _present(pattern, provision) and not _present(pattern, claim):
            defects.append(
                f"пересказ обобщает узкое условие нормы: {explanation}, но в формулировке это ограничение отсутствует"
            )

    for pattern, label in _SUBSTANTIVE_ANCHORS:
        if _present(pattern, claim) and not _present(pattern, provision):
            defects.append(f"пересказ вводит требование «{label}», которого нет в тексте нормы")

    return defects


def is_paraphrase_safe(statement: str, provision_text: str) -> bool:
    return not paraphrase_defects(statement, provision_text)


def quote_is_usable(provision_text: str, *, min_chars: int = 40) -> bool:
    return len((provision_text or "").strip()) >= min_chars


def verified_claim_line(statement: str, article: str, provision_text: str, source_url: str) -> str:
    quote = " ".join((provision_text or "").split())[:400]
    return f"{statement} [основание: {article}; текст нормы: «{quote}»; источник: {source_url}]"
