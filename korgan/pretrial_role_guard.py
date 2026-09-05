"""Кто кому пишет в претензии и в ответе на неё.

Что было видно клиенту
----------------------
Заявка «досудебная претензия» выдала документ с заголовком «ОТВЕТ НА
ПРЕТЕНЗИЮ»: должник значился отправителем, кредитор — адресатом, а в тексте
стояло «задолженность не оспариваем». Кредитор получил письмо, написанное от
имени его должника.

Почему одной починки маршрутизации мало
---------------------------------------
Маршрутизация решает, какой конвейер запустить. Но роли сторон и заголовок
пишет модель, и она видит ту же фабулу, где обе стороны названы. Ошибка в
одном поле — и документ снова говорит не от того лица. Здесь эти два поля
проверяются детерминированно, по фактам самого черновика, а не по намерению
конвейера.

Правило
-------
* ``pretrial``: отправитель — кредитор (тот, кто требует), адресат — должник.
  Заголовок не вправе называть документ ответом, а текст — содержать
  признаний должника («задолженность не оспариваем», «готовы погасить»).
* ``pretrial_response``: отправитель — получатель исходной претензии, адресат —
  тот, кто её направил. Заголовок не вправе называть документ претензией.

Нарушение не «исправляется» перестановкой сторон: поменять местами реквизиты
значило бы дописать за юриста то, чего в материалах нет. Документ помечается
как непрошедший проверку с точной причиной — fail-closed.
"""

from __future__ import annotations

import re

from korgan.legal_types import VerificationStatus

#: Заголовок ответа на претензию внутри самой претензии — и наоборот.
_RESPONSE_TITLE_RE = re.compile(
    r"(?i)(?:ответ\w*\s+на\s+(?:досудебн\w*\s+)?претензи|"
    r"возражен\w*\s+на\s+(?:досудебн\w*\s+)?претензи|"
    r"отзыв\w*\s+на\s+(?:досудебн\w*\s+)?претензи|"
    r"талап\w*\s+(?:жауап|қарсылық))"
)
_PRETRIAL_TITLE_RE = re.compile(
    r"(?i)(?:^|\b)(?:досудебн\w*\s+)?претензи\w*"
)

#: Признания должника: в претензии кредитора их быть не может по смыслу
#: документа — он требует исполнения, а не соглашается с требованием.
_DEBTOR_ADMISSION_RE = re.compile(
    r"(?i)(?:не\s+оспарива\w*\s+(?:задолженност\w*|долг\w*|сумм\w*|требован\w*)|"
    r"задолженност\w*\s+не\s+оспарива\w*|долг\s+не\s+оспарива\w*|"
    r"призна[её]м\s+(?:задолженност\w*|долг\w*|требован\w*)|"
    r"готов\w*\s+(?:обсуди\w*|рассмотре\w*)\s+(?:погашен\w*|график\w*|рассрочк\w*)|"
    r"готов\w*\s+погаси\w*)"
)

#: Требование исполнения: этим претензия и отличается от ответа на неё.
_DEMAND_RE = re.compile(
    r"(?i)(?:требуе\w*|треб\w*\s+(?:оплат|погаш|уплат|возврат)|"
    r"просим\s+(?:оплат\w*|погаси\w*|уплати\w*|возврати\w*)|"
    r"обяза\w*\s+(?:оплат|погаси|уплати)|талап\s+ет\w*)"
)

TITLE_ROLE_NOTE = (
    "Роли сторон в документе не соответствуют выбранному типу: "
    "проверьте, кто отправитель, а кто адресат."
)


def _text(values: object) -> str:
    if isinstance(values, (list, tuple)):
        return " ".join(str(item or "") for item in values)
    return str(values or "")


def pretrial_role_issues(draft: object) -> list[str]:
    """Замечания к досудебной претензии: она должна исходить от кредитора."""
    issues: list[str] = []
    title = _text(getattr(draft, "title", ""))
    if _RESPONSE_TITLE_RE.search(title):
        issues.append(
            "досудебная претензия озаглавлена как ответ на претензию — "
            "документ подготовлен от имени не той стороны"
        )

    body = "\n".join(
        [
            _text(getattr(draft, "facts", [])),
            _text(getattr(draft, "demands", [])),
            _text(getattr(draft, "consequences", [])),
        ]
    )
    if _DEBTOR_ADMISSION_RE.search(body):
        issues.append(
            "в досудебной претензии есть признание долга со стороны отправителя — "
            "так пишет должник, а не кредитор, заявляющий требование"
        )
    return issues


def pretrial_response_role_issues(draft: object) -> list[str]:
    """Замечания к ответу на претензию: он исходит от получателя требования."""
    issues: list[str] = []
    title = _text(getattr(draft, "title", ""))
    if title.strip() and not _RESPONSE_TITLE_RE.search(title) and _PRETRIAL_TITLE_RE.search(title):
        issues.append(
            "ответ на претензию озаглавлен как сама претензия — "
            "документ подготовлен от имени не той стороны"
        )

    position = "\n".join(
        [
            _text(getattr(draft, "position", [])),
            _text(getattr(draft, "objections", [])),
            _text(getattr(draft, "response_terms", [])),
        ]
    )
    if _DEMAND_RE.search(position) and not _RESPONSE_TITLE_RE.search(title):
        issues.append(
            "ответ на претензию сформулирован как требование к другой стороне — "
            "проверьте, от чьего имени готовится документ"
        )
    return issues


def enforce_pretrial_roles(draft: object) -> list[str]:
    """Пометить претензию, если роли сторон не сходятся с типом документа."""
    return _apply(draft, pretrial_role_issues(draft))


def enforce_pretrial_response_roles(draft: object) -> list[str]:
    """Пометить ответ на претензию, если роли сторон перевёрнуты."""
    return _apply(draft, pretrial_response_role_issues(draft))


def _apply(draft: object, issues: list[str]) -> list[str]:
    if not issues:
        return []
    notes = list(getattr(draft, "verification_notes", []) or [])
    for issue in issues:
        if issue not in notes:
            notes.append(issue)
    draft.verification_notes = notes
    draft.status = VerificationStatus.NEEDS_VERIFICATION
    return issues
