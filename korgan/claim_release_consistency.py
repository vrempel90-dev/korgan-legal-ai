"""Иск не должен противоречить сам себе в том, что он уже установил.

Что видел юрист в готовом документе
-----------------------------------
* Суд назван уверенно — «Специализированный межрайонный экономический суд
  города Алматы» — и тут же в перечне задач стоит «подтвердить точное
  наименование суда и территориальную подсудность». Два взаимоисключающих
  утверждения об одном факте: либо суд установлен, либо нет.
* Госпошлина рассчитана детерминированно, а рядом висит «уточнить размер
  государственной пошлины». Клиент не знает, платить ему 135 000 или ждать.
* В разделе «Ходатайства» стоят «ходатайство об уточнении суда» и «ходатайство
  об истребовании документа об оплате государственной пошлины» — процессуальные
  документы, которых в деле нет и которые истец подаёт не сам себе. Это
  внутренние действия проверки, вынесенные в лицо суду.
* Хронология досудебного порядка повторена дважды: один раз в фактах, второй —
  в разделе о соблюдении досудебного порядка.

Что делает этот слой
--------------------
Ничего не досочиняет. Он снимает противоречие в пользу того, что уже
установлено детерминированно: если суд подтверждён — исчезает задача его
подтвердить; если пошлина посчитана — исчезает задача уточнить её размер. Если
же факт не установлен, задача остаётся, а поле документа обязано нести
видимую пометку, а не уверенную формулировку.
"""

from __future__ import annotations

import re

from korgan.legal_calc import NEEDS_CALCULATION_MARKER

#: Любая видимая пометка «здесь нужен человек». Одного вхождения достаточно,
#: чтобы считать поле неустановленным.
UNRESOLVED_MARKER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ\s+(?:УТОЧНЕНИЯ|ПРОВЕРКИ|РАСЧ[ЕЁ]ТА|ДОБАВИТЬ)|"
    r"НАҚТЫЛАУ\s+ҚАЖЕТ|ТЕКСЕРУ\s+ҚАЖЕТ|МЕМЛЕКЕТТІК\s+БАЖДЫ\s+ЕСЕПТЕУ\s+ҚАЖЕТ)",
    re.IGNORECASE,
)

#: Задачи про суд и подсудность — во всех формулировках, которые ставят слои.
_COURT_NOTE_RE = re.compile(
    r"(?i)(?:наименовани\w*\s+суда|подсудност\w*|компетенци\w*\s+экономическ\w*\s+суда|"
    r"точн\w*\s+суд\b|выбор\w*\s+экономическ\w*\s+суда|"
    r"относится\s+к\s+гражданскому/экономическому\s+судопроизводству)"
)

#: Задачи про размер пошлины. Уплата и приложение квитанции — другое: это
#: действие истца перед подачей, оно остаётся и при посчитанной сумме.
_DUTY_AMOUNT_NOTE_RE = re.compile(
    r"(?i)(?:размер\w*\s+государственн\w*\s+пошлин\w*|"
    r"государственная\s+пошлина\s+требует\s+проверки|"
    r"уточнить\s+размер\s+государственной\s+пошлины|"
    r"госпошлина\s+не\s+определена|"
    r"не\s+определена\s+госпошлина)"
)

#: Расходы на представителя. Они взыскиваются только по подтверждённому
#: договору и оплате, поэтому строка без опоры в материалах дела — это
#: требование, которое суд отклонит, а до того испортит впечатление от иска.
_REPRESENTATIVE_COST_RE = re.compile(
    r"(?i)(?:расход\w*\s+(?:на|по)\s+(?:(?:оплат\w*|услуг\w*)\s+){0,2}"
    r"(?:представител\w*|адвокат\w*|юрист\w*|юридическ\w*)|"
    r"öкіл\w*\s+шығын\w*|өкіл\w*\s+шығын\w*)"
)
_REPRESENTATIVE_PROOF_RE = re.compile(
    r"(?i)(?:договор\w*[^.\n]{0,60}(?:юридическ\w*|представител\w*|адвокат\w*)|"
    r"(?:юридическ\w*|представител\w*|адвокат\w*)[^.\n]{0,60}договор\w*|"
    r"квитанц\w*|платежн\w*\s+поручен\w*|акт\w*\s+оказанн\w*\s+услуг)"
)

#: Внутренний словарь конвейера. В судебном тексте эти слова не значат ничего,
#: а читаются как признание, что документ не дописан.
_INTERNAL_TEXT_RE = re.compile(
    r"(?i)(?:FILING_ACTION|SENIOR_PREFLIGHT_SCORE|VERIFIED_COURT|KORGAN QUALITY|"
    r"NEEDS_VERIFICATION|source-bound|verification_notes|правовая\s+оценка\s+не\s+проведена|"
    r"позиция\s+не\s+определена)"
)

#: Ходатайства, которые на деле являются внутренними действиями проверки.
#: «Уточнить суд» суд не удовлетворяет — он возвращает иск. «Истребовать
#: документ об оплате собственной госпошлины» истец адресует сам себе.
_INTERNAL_MOTION_RE = re.compile(
    r"(?i)(?:уточнени\w*\s+(?:наименовани\w*\s+)?суда|уточнени\w*\s+подсудност\w*|"
    r"истребовани\w*[^.]{0,80}(?:об\s+оплате|об\s+уплате)\s+государственн\w*\s+пошлин\w*|"
    r"истребовани\w*[^.]{0,60}квитанц\w*[^.]{0,40}пошлин\w*|"
    r"подтверждени\w*\s+(?:точн\w*\s+)?наименовани\w*\s+суда|"
    r"проверк\w*\s+(?:правов\w*\s+основани|ссылок\s+на\s+стать))"
)


def _lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item or "") for item in values]


def court_is_resolved(draft: object) -> bool:
    """Назван ли суд так, что иск можно подать без дополнительного решения."""
    court = str(getattr(draft, "court", "") or "").strip()
    return bool(court) and not UNRESOLVED_MARKER_RE.search(court)


def state_duty_is_resolved(draft: object) -> bool:
    """Установлен ли размер пошлины (в том числе как подтверждённая льгота)."""
    duty = str(getattr(draft, "state_duty", "") or "").strip()
    if not duty or duty == NEEDS_CALCULATION_MARKER:
        return False
    return not UNRESOLVED_MARKER_RE.search(duty)


def _drop(notes: list[str], predicate) -> list[str]:
    return [note for note in notes if not predicate(note)]


def _normalized(line: str) -> str:
    return re.sub(r"\W+", "", str(line or "").lower())


def _dedupe_narrative(lines: list[str]) -> list[str]:
    """Убрать повтор одного и того же абзаца фабулы.

    Хронология досудебного порядка попадала в документ дважды: один раз в
    фактах, второй — в разделе о его соблюдении. Судья читает одно и то же
    описание подряд и не понимает, идёт ли речь о двух разных претензиях.
    """
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = _normalized(line)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(line)
    return result


#: Профессиональные разделы иска, которые обязаны говорить о своём предмете, а
#: не пересказывать фабулу. Досудебный порядок повторял хронологию претензии
#: слово в слово: судья читал одно и то же описание дважды подряд и не понимал,
#: идёт ли речь о двух разных претензиях.
_ECHO_FIELDS = ("jurisdiction_reason", "pretrial_compliance", "reconciliation_measures", "limitation_period")


def _drop_narrative_echo(draft: object) -> None:
    known = {_normalized(line) for line in _lines(getattr(draft, "facts", [])) if _normalized(line)}
    if not known:
        return
    for field in _ECHO_FIELDS:
        value = str(getattr(draft, field, "") or "").strip()
        if value and _normalized(value) in known:
            setattr(draft, field, "")


def duplicated_narrative_fields(draft: object) -> list[str]:
    """Разделы, дословно повторяющие уже изложенную фабулу."""
    known = {_normalized(line) for line in _lines(getattr(draft, "facts", [])) if _normalized(line)}
    if not known:
        return []
    return [
        field for field in _ECHO_FIELDS
        if _normalized(str(getattr(draft, field, "") or "")) in known
        and str(getattr(draft, field, "") or "").strip()
    ]


def unsupported_cost_requests(draft: object, case_context: str = "") -> list[str]:
    """Требования о расходах на представителя, не опертые на материалы дела."""
    proof_text = "\n".join(
        [str(case_context or ""), *_lines(getattr(draft, "attachments", [])), *_lines(getattr(draft, "calculation", []))]
    )
    if _REPRESENTATIVE_PROOF_RE.search(proof_text):
        return []
    return [
        request for request in _lines(getattr(draft, "requests", []))
        if _REPRESENTATIVE_COST_RE.search(request)
    ]


def internal_text_leaks(draft: object) -> list[str]:
    """Служебные слова конвейера, попавшие в обращённый к суду текст."""
    body = [
        *_lines(getattr(draft, "facts", [])),
        *_lines(getattr(draft, "legal_basis", [])),
        *_lines(getattr(draft, "requests", [])),
        *_lines(getattr(draft, "calculation", [])),
        *_lines(getattr(draft, "motions", [])),
        *_lines(getattr(draft, "attachments", [])),
    ]
    return [line for line in body if _INTERNAL_TEXT_RE.search(line)]


#: Чем заменяется уверенно названный, но неподтверждённый суд. Точное
#: наименование, которого никто не проверил, судья читает как утверждение
#: истца о подсудности — и возвращает иск, если оно неверно.
UNVERIFIED_COURT_PLACEHOLDER = (
    "[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда по надлежащей подсудности]"
)
UNVERIFIED_COURT_ACTION = (
    "FILING_ACTION: подтвердить точное наименование суда и территориальную "
    "подсудность по официальному перечню судов перед подачей."
)


def enforce_verified_court_only(draft: object, case_context: str = "", research: object = None) -> bool:
    """Оставить в документе только подтверждённое наименование суда.

    Два состояния взаимоисключающи. Суд либо подтверждён — материалами дела или
    записью ``VERIFIED_COURT`` из source-bound исследования — и тогда называется
    прямо, либо не подтверждён — и тогда не называется вовсе. Раньше документ
    делал и то и другое сразу: печатал «Специализированный межрайонный
    экономический суд города Алматы» и рядом сообщал, что это наименование ничем
    не подтверждено. Подставить название за юриста нельзя, поэтому неподтверждённый
    суд заменяется видимой пометкой и одной задачей.

    Возвращает признак «суд подтверждён».
    """
    from korgan.document_quality import _court_is_concrete, _court_supported
    from korgan.legal_types import LegalResearch, VerificationStatus

    court = str(getattr(draft, "court", "") or "").strip()
    if not court or not _court_is_concrete(court):
        return False

    if research is None:
        research = LegalResearch(
            status=VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[],
            procedural_requirements=[],
            verified_claims=[],
            unverified_claims=[],
            source_urls=[],
            notes=[],
        )
    if _court_supported(str(case_context or ""), research, court):
        return True

    draft.court = UNVERIFIED_COURT_PLACEHOLDER
    notes = _lines(getattr(draft, "verification_notes", []))
    notes = _drop(notes, lambda note: bool(_COURT_NOTE_RE.search(note)))
    notes.append(UNVERIFIED_COURT_ACTION)
    draft.verification_notes = list(dict.fromkeys(notes))
    draft.status = VerificationStatus.NEEDS_VERIFICATION
    return False


def enforce_release_consistency(draft: object, case_context: str = "", research: object = None) -> None:
    """Снять противоречия между установленными фактами и перечнем задач."""
    enforce_verified_court_only(draft, case_context, research)
    notes = _lines(getattr(draft, "verification_notes", []))

    if court_is_resolved(draft):
        notes = _drop(notes, lambda note: bool(_COURT_NOTE_RE.search(note)))
    if state_duty_is_resolved(draft):
        notes = _drop(notes, lambda note: bool(_DUTY_AMOUNT_NOTE_RE.search(note)))

    draft.verification_notes = list(dict.fromkeys(note for note in notes if note.strip()))

    motions = _lines(getattr(draft, "motions", []))
    if motions:
        draft.motions = _dedupe_narrative([
            motion for motion in motions
            if motion.strip() and not _INTERNAL_MOTION_RE.search(motion)
        ])

    facts = _lines(getattr(draft, "facts", []))
    if facts:
        draft.facts = _dedupe_narrative(facts)
    _drop_narrative_echo(draft)

    # Расходы на представителя без договора и оплаты в материалах — требование,
    # которое суд отклонит. Заявлять его «на всякий случай» нельзя.
    unsupported = set(unsupported_cost_requests(draft, case_context))
    if unsupported:
        draft.requests = [
            request for request in _lines(getattr(draft, "requests", []))
            if request not in unsupported
        ]


def contradictory_release_issues(draft: object) -> list[str]:
    """Оставшиеся противоречия — для теста и для журнала выпуска."""
    issues: list[str] = []
    notes = " \n".join(_lines(getattr(draft, "verification_notes", [])))

    if court_is_resolved(draft) and _COURT_NOTE_RE.search(notes):
        issues.append("суд назван уверенно и одновременно помечен как требующий уточнения")
    if state_duty_is_resolved(draft) and _DUTY_AMOUNT_NOTE_RE.search(notes):
        issues.append("размер госпошлины рассчитан и одновременно помечен как требующий уточнения")
    for motion in _lines(getattr(draft, "motions", [])):
        if _INTERNAL_MOTION_RE.search(motion):
            issues.append(f"внутреннее действие проверки оформлено как ходатайство суду: {motion}")

    facts = _lines(getattr(draft, "facts", []))
    if len(facts) != len({_normalized(line) for line in facts if _normalized(line)}):
        issues.append("фабула повторена дважды в разделе фактических обстоятельств")
    for field in duplicated_narrative_fields(draft):
        issues.append(f"раздел «{field}» дословно повторяет уже изложенную фабулу")

    for leak in internal_text_leaks(draft):
        issues.append(f"служебный текст конвейера попал в судебный документ: {leak}")
    return issues
