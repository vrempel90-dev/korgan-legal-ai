"""Материальная опора требования обязана дожить до готового документа.

Что было в журнале прода
------------------------
Исследование подтверждало норму о существе долга — обязанность покупателя
оплатить принятый товар, — а в готовом иске раздел «Правовое обоснование»
опирался только на процессуальные статьи: подсудность, форму иска, госпошлину.
Судья читал документ, в котором не сказано, из какой нормы вытекает сама
обязанность заплатить.

Как норма терялась
------------------
``claim_filing_accuracy`` не дополняет правовое обоснование, а пересобирает его
целиком: ``draft.legal_basis = accepted``. Всё, что не прошло сверку с
корпусом или не имело связки «статья + дословная выдержка + официальный
источник», отбрасывается. Отбрасывание правильно — выдумывать норму нельзя, —
но молчаливым оно быть не может: иск без материального основания
неотличим по виду от иска с ним.

Что делает этот слой
--------------------
Ничего не дописывает в документ. Он отвечает на один вопрос: осталась ли в
правовом обосновании хоть одна норма о существе требования. Процессуальная
статья таким основанием не является и заменить его не может. Если материальной
опоры нет, документ перестаёт быть готовым к подаче и прямо называет, что
именно потеряно, — вместо тихой выдачи иска, который не доказывает сам себя.
"""

from __future__ import annotations

import re

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

SUBSTANTIVE_GAP_NOTE = (
    "Правовое обоснование опирается только на процессуальные нормы: "
    "норма о существе требования не выпущена в судебный текст."
)
SUBSTANTIVE_LOST_NOTE = (
    "Подтверждённая норма о существе требования не дошла до правового "
    "обоснования документа: {articles}."
)

#: Процессуальные и фискальные акты. Они определяют, как подать иск и сколько
#: стоит подача, но не то, почему ответчик обязан платить.
_PROCEDURAL_ACT_RE = re.compile(
    r"(?i)(?:\bГПК\s*РК\b|гражданск\w*\s+процессуальн\w*\s+кодекс|"
    r"\bНК\s*РК\b|налогов\w*\s+кодекс|"
    r"\bАППК\b|административн\w*\s+процедурно)"
)

#: Акты материального права, на которые опирается требование по существу.
_SUBSTANTIVE_ACT_RE = re.compile(
    r"(?i)(?:\bГК\s*РК\b|гражданск\w*\s+кодекс(?!\w*\s+процессуальн)|"
    r"\bТК\s*РК\b|трудов\w*\s+кодекс|"
    r"защит\w*\s+прав\w*\s+потребител\w*|"
    r"\bЗРК\b|закон\w*\s+республики\s+казахстан)"
)

#: Номер статьи: без него строка правового обоснования вообще не является
#: ссылкой на норму.
_ARTICLE_RE = re.compile(r"(?i)(?:стать[яеию]|ст\.)\s*\d+")

#: Требования, для которых материальная опора обязательна: любое взыскание
#: денег или исполнения по обязательству. Процессуальные пункты просительной
#: части (расходы, пошлина) сами по себе такой опоры не требуют.
_SUBSTANTIVE_RELIEF_RE = re.compile(
    r"(?i)(?:взыска\w*|обяза\w*|расторг\w*|признать\b|возврат\w*|"
    r"истреб\w*\s+имуществ|өндір\w*|міндетте\w*)"
)
_PROCEDURAL_RELIEF_RE = re.compile(
    r"(?i)(?:госпошлин\w*|государственн\w*\s+пошлин\w*|судебн\w*\s+расход\w*|"
    r"мемлекеттік\s+баж|сот\s+шығын\w*)"
)


def _lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [" ".join(str(item or "").split()) for item in values if str(item or "").strip()]


def is_substantive_basis_line(line: str) -> bool:
    """Ссылается ли строка правового обоснования на норму материального права."""
    text = str(line or "")
    if not _ARTICLE_RE.search(text):
        return False
    if not _SUBSTANTIVE_ACT_RE.search(text):
        return False
    # «ГК РК» внутри строки, где рядом назван ГПК, ещё не делает её
    # материальной: ссылка может перечислять оба кодекса подряд. Материальной
    # считается только та, где процессуального акта нет вовсе.
    return not _PROCEDURAL_ACT_RE.search(text)


def requires_substantive_basis(draft: ClaimDraft) -> bool:
    """Есть ли в просительной части требование по существу спора."""
    for request in _lines(getattr(draft, "requests", [])):
        if _PROCEDURAL_RELIEF_RE.search(request):
            continue
        if _SUBSTANTIVE_RELIEF_RE.search(request):
            return True
    return False


def substantive_basis_lines(draft: ClaimDraft) -> list[str]:
    """Строки правового обоснования, которые действительно опираются на норму."""
    return [line for line in _lines(getattr(draft, "legal_basis", [])) if is_substantive_basis_line(line)]


def verified_substantive_articles(research: LegalResearch) -> list[str]:
    """Номера материальных статей, подтверждённых исследованием."""
    found: list[str] = []
    for line in _lines(getattr(research, "verified_claims", [])):
        if "официальный перечень судов" in line.lower():
            continue
        if not is_substantive_basis_line(line):
            continue
        match = _ARTICLE_RE.search(line)
        if match is None:
            continue
        label = " ".join(match.group(0).split())
        if label not in found:
            found.append(label)
    return found


def substantive_basis_issues(research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Что именно не так с материальной опорой готового документа."""
    if not requires_substantive_basis(draft):
        return []

    present = substantive_basis_lines(draft)
    if present:
        return []

    verified = verified_substantive_articles(research)
    if verified:
        return [SUBSTANTIVE_LOST_NOTE.format(articles="; ".join(verified[:4]))]
    return [SUBSTANTIVE_GAP_NOTE]


def enforce_substantive_basis(research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Не выпускать как готовый иск, у которого нет материального основания."""
    issues = substantive_basis_issues(research, draft)
    if not issues:
        return []

    notes = list(getattr(draft, "verification_notes", []) or [])
    for issue in issues:
        if issue not in notes:
            # Первым в перечне: отсутствие опоры требования важнее любого
            # пробела в реквизитах, а хвост длинного перечня клиент не читает.
            notes.insert(0, issue)
    draft.verification_notes = notes
    draft.status = VerificationStatus.NEEDS_VERIFICATION
    return issues
