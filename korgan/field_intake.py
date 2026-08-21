"""Turn a user's direct answer into something the preflight check can see.

The loop that trapped users was here. `claim_preflight` reads a *narrative*: it
looks for «дата рождения» and then a date near it, for «истец» and an ИИН in the
same window. That works on a case description. It cannot work on an answer,
because an answer does not repeat the question — asked for a date of birth, a
person types «03.03.1999» and nothing else. The value was stored correctly, the
check simply had no marker to find it by, so the same field stayed missing and
the bot asked again, forever.

The fix is not to loosen the check — its markers are what stop a defendant's
address from satisfying the claimant's. It is to record the answer in the form
the check reads: «Дата рождения истца: 03.03.1999». This module does that
translation, and it refuses quietly-wrong input loudly: a value that cannot be
parsed as its field's type comes back as an explicit format error with an
example, never as silence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

LOGGER = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*$")
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*$")
_DIGITS_RE = re.compile(r"\d")
_IIN_RE = re.compile(r"^\s*(?:\d[\s-]?){12}\s*$")
_NAME_RE = re.compile(r"^\s*[А-ЯЁA-Z][а-яёa-z'’-]+(?:\s+[А-ЯЁA-Z][а-яёa-z'’-]+){1,2}\s*$")
_ENTITY_NAME_RE = re.compile(
    r"^\s*(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ИП|товарищество\s+с\s+ограниченной\s+ответственностью|акционерное\s+общество)\s+.+$",
    re.IGNORECASE,
)
_IBAN_RE = re.compile(r"\bKZ[0-9A-Z]{16,18}\b", re.IGNORECASE)

_ADDRESS_TOKENS = (
    "ул.", "улица", "мкр", "микрорайон", "проспект", "пр-т", "д.", "дом", "кв.",
    "квартира", "г.", "город", "село", "район", "область", "шоссе", "переулок",
)
_BANK_TOKENS = ("iban", "kz", "банк", "бик", "счет", "счёт", "kaspi", "halyk")


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One collectable field: how to recognise it and how to record it."""

    label: str          # exactly as claim_preflight reports it in `missing`
    canonical: str      # prefix written into the case so preflight finds it
    kind: str           # date | iin | name | entity_name | address | bank | text
    example: str
    hint: str


def _spec(label: str, canonical: str, kind: str, example: str, hint: str) -> FieldSpec:
    return FieldSpec(label, canonical, kind, example, hint)


FIELD_SPECS: tuple[FieldSpec, ...] = (
    _spec("дата рождения истца", "Дата рождения истца", "date",
          "15.06.1990", "дата в формате ДД.ММ.ГГГГ"),
    _spec("ИИН истца", "ИИН истца", "iin",
          "900101300123", "ИИН — ровно 12 цифр"),
    _spec("БИН истца", "БИН истца", "iin",
          "123456789012", "БИН — ровно 12 цифр"),
    _spec("ФИО истца полностью", "ФИО истца", "name",
          "Иванов Иван Иванович", "фамилия, имя и отчество полностью"),
    _spec("полное наименование истца", "Полное наименование истца", "entity_name",
          "ТОО «Астана Логистик»", "организационно-правовая форма и наименование"),
    _spec("адрес места жительства истца", "Адрес места жительства истца", "address",
          "г. Алматы, ул. Абая, д. 15, кв. 3", "город, улица, дом, квартира"),
    _spec("место нахождения истца", "Место нахождения истца", "address",
          "г. Алматы, ул. Абая, д. 15", "город, улица, дом"),
    _spec("банковские реквизиты истца", "Банковские реквизиты истца", "bank",
          "IBAN KZ123456789012345678, АО «Банк»", "IBAN и наименование банка"),
    _spec("ФИО ответчика полностью", "ФИО ответчика", "name",
          "Петров Пётр Петрович", "фамилия, имя и отчество полностью"),
    _spec("адрес места жительства ответчика", "Адрес места жительства ответчика", "address",
          "г. Астана, ул. Кенесары, д. 40, кв. 12", "город, улица, дом, квартира"),
    _spec("полное наименование ответчика", "Полное наименование ответчика", "entity_name",
          "ТОО «КурылысСтройИнвест»", "организационно-правовая форма и полное наименование"),
    _spec("БИН ответчика", "БИН ответчика", "iin",
          "150640012233", "БИН — ровно 12 цифр"),
    _spec("место нахождения ответчика", "Место нахождения ответчика", "address",
          "г. Алматы, Алатауский район, ул. Момышулы, 5", "город, район, улица и номер здания"),
)

SPEC_BY_LABEL: dict[str, FieldSpec] = {spec.label: spec for spec in FIELD_SPECS}


@dataclass(slots=True)
class Intake:
    """What a single user answer produced."""

    recorded: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    leftover: list[str] = field(default_factory=list)

    @property
    def progressed(self) -> bool:
        return bool(self.recorded)

    def as_case_text(self) -> str:
        return "\n".join([*self.recorded, *self.leftover])


def _segments(text: str) -> list[str]:
    parts = [part.strip(" \t·-") for part in re.split(r"[\n;]+", text or "")]
    return [part for part in parts if part]


def normalize_date(value: str) -> str | None:
    """Accept DD.MM.YYYY, D/M/YYYY and ISO, return DD.MM.YYYY."""
    match = _DATE_RE.match(value)
    if match:
        day, month, year = (int(part) for part in match.groups())
    else:
        iso = _ISO_DATE_RE.match(value)
        if not iso:
            return None
        year, month, day = (int(part) for part in iso.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if not (1900 <= parsed.year <= datetime.now().year):
        return None
    return parsed.strftime("%d.%m.%Y")


def normalize_iin(value: str) -> str | None:
    if not _IIN_RE.match(value):
        return None
    digits = "".join(_DIGITS_RE.findall(value))
    return digits if len(digits) == 12 else None


def _looks_like_address(value: str) -> bool:
    lowered = f" {value.lower()} "
    if not any(token in lowered for token in _ADDRESS_TOKENS):
        return False
    return bool(_DIGITS_RE.search(value)) or "," in value


def _looks_like_bank(value: str) -> bool:
    lowered = value.lower()
    return bool(_IBAN_RE.search(value)) or any(token in lowered for token in _BANK_TOKENS)


def detect_kind(value: str) -> str | None:
    """Best guess at what a bare value is, or None when it is not obvious."""
    if normalize_date(value):
        return "date"
    if normalize_iin(value):
        return "iin"
    if _ENTITY_NAME_RE.match(value):
        return "entity_name"
    if _looks_like_bank(value) and not _looks_like_address(value):
        return "bank"
    if _looks_like_address(value):
        return "address"
    if _NAME_RE.match(value):
        return "name"
    return None


def _normalize_for(spec: FieldSpec, value: str) -> tuple[str | None, str | None]:
    """Return (normalized value, error message)."""
    if spec.kind == "date":
        normalized = normalize_date(value)
        if not normalized:
            return None, (
                f"Не получилось распознать «{spec.label}» в значении «{value}». "
                f"Пришлите {spec.hint}, например: {spec.example}"
            )
        return normalized, None

    if spec.kind == "iin":
        normalized = normalize_iin(value)
        if not normalized:
            return None, (
                f"Не получилось распознать «{spec.label}» в значении «{value}». "
                f"Нужен {spec.hint}, например: {spec.example}"
            )
        return normalized, None

    if spec.kind == "name" and not _NAME_RE.match(value):
        return None, (
            f"Не получилось распознать «{spec.label}» в значении «{value}». "
            f"Укажите {spec.hint}, например: {spec.example}"
        )

    if spec.kind == "entity_name" and not _ENTITY_NAME_RE.match(value):
        return None, (
            f"Не получилось распознать «{spec.label}» в значении «{value}». "
            f"Укажите {spec.hint}, например: {spec.example}"
        )

    if spec.kind == "address" and not _looks_like_address(value):
        return None, (
            f"Не получилось распознать «{spec.label}» в значении «{value}». "
            f"Укажите {spec.hint}, например: {spec.example}"
        )

    return value.strip(), None


def _already_labelled(segment: str, spec: FieldSpec) -> bool:
    """True when the user wrote the field name themselves («ИИН истца 9001...»)."""
    head = segment.lower()[: len(spec.canonical) + 24]
    keywords = [word for word in spec.canonical.lower().split() if len(word) > 2]
    return all(word in head for word in keywords) if keywords else False


def normalize_answer(pending: list[str], text: str) -> Intake:
    """Interpret a user's reply to the "missing fields" prompt.

    ``pending`` is the field list the bot last asked for, in the order it asked.
    """
    intake = Intake()
    specs = [SPEC_BY_LABEL[label] for label in pending if label in SPEC_BY_LABEL]
    remaining = list(specs)
    segments = _segments(text)

    for segment in segments:
        labelled = next((spec for spec in remaining if _already_labelled(segment, spec)), None)
        if labelled is not None:
            intake.recorded.append(segment)
            intake.matched.append(labelled.label)
            remaining.remove(labelled)
            continue

        kind = detect_kind(segment)
        candidates = [spec for spec in remaining if spec.kind == kind] if kind else []

        if len(candidates) > 1:
            names = ", ".join(f"«{spec.label}»" for spec in candidates)
            intake.errors.append(
                f"Значение «{segment}» подходит сразу к нескольким полям: {names}. "
                f"Подпишите его, например: {candidates[0].canonical}: {segment}"
            )
            continue

        if len(candidates) == 1:
            spec = candidates[0]
            value, error = _normalize_for(spec, segment)
            if error:
                intake.errors.append(error)
                continue
            intake.recorded.append(f"{spec.canonical}: {value}")
            intake.matched.append(spec.label)
            remaining.remove(spec)
            continue

        if len(remaining) == 1 and len(segments) == 1:
            spec = remaining[0]
            value, error = _normalize_for(spec, segment)
            if error:
                intake.errors.append(error)
                continue
            intake.recorded.append(f"{spec.canonical}: {value}")
            intake.matched.append(spec.label)
            remaining.clear()
            continue

        intake.leftover.append(segment)

    return intake


def format_hint(pending: list[str]) -> str:
    """A worked example of how to answer the current set of fields."""
    specs = [SPEC_BY_LABEL[label] for label in pending if label in SPEC_BY_LABEL]
    if not specs:
        return ""
    lines = [f"{spec.canonical}: {spec.example}" for spec in specs[:6]]
    return "\n".join(lines)
