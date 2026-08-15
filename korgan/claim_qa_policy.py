"""Что действительно блокирует выдачу иска, а что становится NEEDS_VERIFICATION.

Fail-closed в KORGAN означает «не утверждать недоказанное», а не «не выдавать
документ». Раньше любое замечание финального QA из категорий
``critical_errors`` и ``unsupported_legal_claims`` после единственного
ремонтного прохода приводило к ``CourtDocumentQualityError`` и полному отказу.
Для кейса «долг по расписке» это давало ложную блокировку: расписка —
самостоятельное письменное доказательство передачи денег по займу между
физлицами (ГК РК требует письменную форму, расписка её удовлетворяет), а
претензионный порядок для такого требования не является общеобязательным по
ГПК РК. Замечание «нет второго доказательства» или «нет претензии» — это повод
поставить пометку в документе, а не повод не выдать документ.

Блокируют выдачу только два класса дефектов:

1. фабрикация и подмена — факт, сумма, дата, роль или документ, которых нет в
   материалах дела;
2. загрязнение судебного текста служебным/чатовым содержимым.

Всё остальное — пробел, который отмечается внутри документа и в QA-заметках.
"""

from __future__ import annotations

from korgan.legal_types import ClaimDraft

# Пробел в доказательствах или в досудебной стадии. Это не дефект проекта:
# документ выдаётся, вопрос уходит в NEEDS_VERIFICATION.
_EVIDENCE_GAP_MARKERS: tuple[str, ...] = (
    "доказательств",
    "расписк",
    "претенз",
    "досудебн",
    "квитанц",
    "выписк",
    "платежн",
    "платёжн",
    "подтверждающ",
    "не приложен",
    "не представлен",
    "не загружен",
    "отсутствует документ",
    "нет документа",
    "оригинал",
    "копи",
)

# Модель выдумала факт или подменила роль/сумму/дату. Это настоящий стоп.
_FABRICATION_MARKERS: tuple[str, ...] = (
    "выдуман",
    "придуман",
    "вымышлен",
    "нет в материалах",
    "отсутствует в материалах",
    "не содержится в материалах",
    "не следует из материалов",
    "противоречит материал",
    "не соответствует материал",
    "перепутан",
    "поменяны местами",
    "подмен",
    "искажен",
    "искажён",
    "неверная сумма",
    "неверная дата",
    "неверно указана сторона",
    "роли сторон",
)

# Служебный/чатовый текст, попавший в судебный документ.
_CONTAMINATION_MARKERS: tuple[str, ...] = (
    "чатов",
    "служебн",
    "markdown",
    "url",
    "needs_verification",
    "можно адаптировать",
    "при наличии",
)

_UNVERIFIED_LAW_MARKER = (
    "[ТРЕБУЕТ УТОЧНЕНИЯ: правовое основание требует проверки по официальному источнику]"
)

_EVIDENCE_NOTE_PREFIX = "Доказательственный пробел (не блокирует выдачу проекта): "
_LAW_NOTE_PREFIX = "Правовое основание не подтверждено официальным источником: "


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def is_evidence_gap(issue: str) -> bool:
    """Замечание об отсутствующем доказательстве/претензии, а не о выдумке."""
    if _matches(issue, _FABRICATION_MARKERS):
        return False
    return _matches(issue, _EVIDENCE_GAP_MARKERS)


def is_blocking_critical_error(issue: str) -> bool:
    """``critical_errors`` блокирует только при фабрикации или загрязнении текста."""
    if _matches(issue, _FABRICATION_MARKERS):
        return True
    if is_evidence_gap(issue):
        return False
    return _matches(issue, _CONTAMINATION_MARKERS)


def split_qa_issues(
    *,
    critical_errors: list[str],
    unsupported_legal_claims: list[str],
    hard_issues: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Разложить замечания QA на блокирующие, доказательственные и правовые.

    ``hard_issues`` — детерминированные проверки :mod:`korgan.production_legal`
    (потерянный ИИН/адрес, служебный текст в теле). Они всегда блокирующие:
    это объективно проверяемые дефекты, а не мнение модели.

    ``unsupported_legal_claims`` больше никогда не блокирует. Неподтверждённая
    норма права — ровно тот случай, для которого существует NEEDS_VERIFICATION.
    """
    blocking = list(hard_issues)
    evidence_gaps: list[str] = []

    for issue in critical_errors:
        if is_blocking_critical_error(issue):
            blocking.append(issue)
        elif is_evidence_gap(issue):
            evidence_gaps.append(issue)
        else:
            # Ни выдумка, ни пробел в доказательствах: не блокируем выдачу,
            # но и не прячем — уйдёт в QA-заметки как есть.
            evidence_gaps.append(issue)

    return (
        list(dict.fromkeys(blocking)),
        list(dict.fromkeys(evidence_gaps)),
        list(dict.fromkeys(unsupported_legal_claims)),
    )


def apply_soft_qa_findings(
    draft: ClaimDraft,
    *,
    evidence_gaps: list[str],
    unsupported_legal_claims: list[str],
) -> None:
    """Внести неблокирующие замечания в документ как NEEDS_VERIFICATION.

    Доказательственные пробелы идут только в QA-заметки: судебный текст не
    должен содержать служебных фраз. Неподтверждённое право дополнительно
    помечается прямо в правовом обосновании, чтобы шапка DOCX показала
    ``PRELIMINARY DRAFT`` и документ нельзя было принять за готовый к подаче.
    """
    for issue in evidence_gaps:
        note = f"{_EVIDENCE_NOTE_PREFIX}{issue}"
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    for issue in unsupported_legal_claims:
        note = f"{_LAW_NOTE_PREFIX}{issue}"
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    if unsupported_legal_claims and _UNVERIFIED_LAW_MARKER not in draft.legal_basis:
        draft.legal_basis.append(_UNVERIFIED_LAW_MARKER)
