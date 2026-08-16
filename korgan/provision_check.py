"""Guard against paraphrasing a legal provision into something it does not say.

The failure this closes: a document cited «часть 4 статьи 166 ГПК РК» correctly —
right act, right article, right part, live official source — and then paraphrased
its content wrongly, turning a requirement to reference *evidence* into a
requirement to reference *statutes*, and promoting a rule that is limited to
filings signed by a representative into a rule about every filing. The article
number was verified; the sentence built on it was not.

Verifying the number is therefore not enough. A verified point must carry the
provision's own words, and the paraphrase must be checked against them. This
module performs the mechanical half of that check:

* a paraphrase without the provision text cannot be `VERIFIED` at all;
* a qualifier that narrows the provision (a subject, a condition, an exception)
  must survive into the paraphrase, otherwise the paraphrase generalised it;
* a substantive term that appears in the paraphrase but nowhere in the
  provision text is a requirement the model added.

These are heuristics over wording, not legal reasoning: they catch the
mechanical drift that produced the defect above, and they fail *soft* — a
finding downgrades the point to NEEDS_VERIFICATION rather than asserting the
paraphrase is wrong. The substantive line-by-line comparison remains the model's
obligation under reference/source-verification.md, and the lawyer's after that.
"""

from __future__ import annotations

import re

# Qualifiers that narrow a provision. If the provision text carries one and the
# paraphrase does not, the paraphrase has widened the rule.
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

# Substantive anchors that are routinely swapped for one another in paraphrase.
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
    """Compare a paraphrase against the provision's own words.

    Returns human-readable findings; an empty list means the mechanical check
    found no drift. It never returns "correct" — only "no drift detected".
    """
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
            defects.append(
                f"пересказ вводит требование «{label}», которого нет в тексте нормы"
            )

    return defects


def is_paraphrase_safe(statement: str, provision_text: str) -> bool:
    return not paraphrase_defects(statement, provision_text)


def quote_is_usable(provision_text: str, *, min_chars: int = 40) -> bool:
    """A provision quote must be substantial enough to check a paraphrase against."""
    return len((provision_text or "").strip()) >= min_chars


def verified_claim_line(statement: str, article: str, provision_text: str, source_url: str) -> str:
    """Format an accepted point so the drafter sees the provision's own words.

    The drafting step must be able to re-check its own wording, so the quote
    travels with the conclusion instead of being dropped after research.
    """
    quote = " ".join((provision_text or "").split())[:400]
    return f"{statement} [основание: {article}; текст нормы: «{quote}»; источник: {source_url}]"
