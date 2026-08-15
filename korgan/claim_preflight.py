from __future__ import annotations

import re
from dataclasses import dataclass


_CLAIMANT_MARKERS = ("истец", "истца", "займодавец", "займодавца", "кредитор")
_DEFENDANT_MARKERS = ("ответчик", "ответчика", "заемщик", "заёмщик", "должник")
_ADDRESS_MARKERS = (
    "адрес", "место жительства", "место нахождения", "проживает", "проживаю", "живу ", "живет", "живёт",
    "ул.", " улица ", "дом ", "д. ", "квартира", "кв.", "мкр", "проспект",
)
_LEGAL_ENTITY_MARKERS = ("тоо", "ао ", "акционерное общество", "юридическое лицо", "бин")
_DATE_RE = re.compile(r"(?<!\d)(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?!\d)")
_IIN_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_NAME_RE = re.compile(r"[А-ЯЁA-Z][а-яёa-z'-]{1,}(?:\s+[А-ЯЁA-Z][а-яёa-z'-]{1,}){1,2}")


@dataclass(frozen=True, slots=True)
class ClaimPreflight:
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing

    def user_message(self) -> str:
        items = "\n".join(f"• {item}" for item in self.missing)
        return (
            "📋 Чтобы KORGAN сразу сформировал корректный иск, не хватает обязательных данных:\n\n"
            f"{items}\n\n"
            "Пришлите недостающие сведения одним сообщением. Я сохраню их в текущее дело и автоматически продолжу подготовку иска.\n\n"
            "ИИН ответчика, его телефон и e-mail укажите только если они вам известны — их отсутствие само по себе не блокирует иск."
        )


def _windows(text: str, markers: tuple[str, ...], radius: int = 220) -> list[str]:
    lowered = text.lower()
    result: list[str] = []
    for marker in markers:
        start = 0
        while True:
            idx = lowered.find(marker, start)
            if idx < 0:
                break
            result.append(text[max(0, idx - radius): min(len(text), idx + len(marker) + radius)])
            start = idx + len(marker)
    return result


def _has_role_bound_name(text: str, markers: tuple[str, ...]) -> bool:
    for window in _windows(text, markers, 120):
        for candidate in _NAME_RE.findall(window):
            lowered = candidate.lower()
            if any(word in lowered for word in ("сообщения пользователя", "материалы дела", "важные факты", "гражданский кодекс")):
                continue
            return True
    return False


def _has_role_bound_iin(text: str, markers: tuple[str, ...]) -> bool:
    for window in _windows(text, markers, 180):
        if _IIN_RE.search(window) and "иин" in window.lower():
            return True
    return False


def _segments(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]


def _looks_like_address(segment: str) -> bool:
    lowered = f" {segment.lower()} "
    return any(token in lowered for token in _ADDRESS_MARKERS)


def _has_role_bound_address(text: str, markers: tuple[str, ...]) -> bool:
    claimant = markers == _CLAIMANT_MARKERS

    # Require party + address in the same compact field/segment. A defendant's
    # address located nearby must never satisfy the claimant requirement.
    for segment in _segments(text):
        lowered = segment.lower()
        if any(marker in lowered for marker in markers) and _looks_like_address(segment):
            return True

    lowered = text.lower()
    if claimant:
        patterns = (
            r"\bмой\s+адрес\b",
            r"\bадрес\s+истц[а-яё]*\b",
            r"\bместо\s+жительства\s+истц[а-яё]*\b",
            r"\bя\s+проживаю\b",
            r"\bя\s+живу\b",
            r"\bпроживаю\s+по\s+адресу\b",
        )
    else:
        patterns = (
            r"\bадрес\s+ответчик[а-яё]*\b",
            r"\bместо\s+жительства\s+ответчик[а-яё]*\b",
            r"\bответчик[а-яё]*.{0,80}\b(?:живет|живёт|проживает)\b",
            r"\bон\s+(?:живет|живёт|проживает)\b",
        )
    return any(re.search(pattern, lowered, flags=re.DOTALL) for pattern in patterns)


def _has_claimant_dob(text: str) -> bool:
    lowered = text.lower()
    for marker in ("дата рождения", "родился", "родилась"):
        idx = lowered.find(marker)
        if idx >= 0 and _DATE_RE.search(text[idx: idx + 100]):
            return True
    return False


def inspect_claim_context(case_context: str) -> ClaimPreflight:
    text = case_context.strip()
    if not text:
        return ClaimPreflight(("описание обстоятельств дела или материалы",))

    claimant_windows = "\n".join(_windows(text, _CLAIMANT_MARKERS, 260)).lower()
    claimant_is_legal_entity = any(marker in claimant_windows for marker in _LEGAL_ENTITY_MARKERS)

    missing: list[str] = []

    if claimant_is_legal_entity:
        if not _has_role_bound_name(text, _CLAIMANT_MARKERS):
            missing.append("полное наименование истца")
        if not _has_role_bound_iin(text, _CLAIMANT_MARKERS):
            missing.append("БИН истца")
        if not _has_role_bound_address(text, _CLAIMANT_MARKERS):
            missing.append("место нахождения истца")
        if "банковск" not in claimant_windows and "iban" not in claimant_windows:
            missing.append("банковские реквизиты истца")
    else:
        if not _has_role_bound_name(text, _CLAIMANT_MARKERS):
            missing.append("ФИО истца полностью")
        if not _has_claimant_dob(text):
            missing.append("дата рождения истца")
        if not _has_role_bound_iin(text, _CLAIMANT_MARKERS):
            missing.append("ИИН истца")
        if not _has_role_bound_address(text, _CLAIMANT_MARKERS):
            missing.append("адрес места жительства истца")

    if not _has_role_bound_name(text, _DEFENDANT_MARKERS):
        missing.append("ФИО ответчика полностью")
    if not _has_role_bound_address(text, _DEFENDANT_MARKERS):
        missing.append("адрес места жительства ответчика")

    return ClaimPreflight(tuple(dict.fromkeys(missing)))
