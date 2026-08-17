from __future__ import annotations

import re
from dataclasses import dataclass


_CLAIMANT_MARKERS = ("истец", "истца", "займодавец", "займодавца", "кредитор")
_DEFENDANT_MARKERS = ("ответчик", "ответчика", "заемщик", "заёмщик", "должник")
_ADDRESS_MARKERS = (
    "адрес", "место жительства", "место нахождения", "проживает", "проживаю", "живу ", "живет", "живёт",
    "ул.", " улица ", "дом ", "д. ", "квартира", "кв.", "мкр", "проспект",
)
_LEGAL_ENTITY_MARKERS = (
    "тоо", "ао ", "акционерное общество", "юридическое лицо", "бин",
    "ргп", "ргу", "кгу", "кгп", "ип ",
)
_DATE_RE = re.compile(r"(?<!\d)(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?!\d)")
_TWELVE_DIGIT_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
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


def _segments(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]


def _party_segments(text: str, markers: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for segment in _segments(text):
        lowered = segment.lower()
        if any(marker in lowered for marker in markers):
            result.append(segment)
    return result


def _party_blocks(text: str, markers: tuple[str, ...]) -> list[str]:
    """Return compact multi-line blocks belonging to one party.

    Telegram users commonly send a party header on one line and its address on
    the next.  Treat subsequent lines as belonging to that party until a line
    explicitly starts the opposite party.  This binds an address to the right
    role without allowing a nearby defendant address to satisfy claimant data
    (or vice versa).
    """
    opposite = _DEFENDANT_MARKERS if markers == _CLAIMANT_MARKERS else _CLAIMANT_MARKERS
    lines = [line.strip() for line in text.splitlines()]
    blocks: list[str] = []
    current: list[str] | None = None

    for line in lines:
        lowered = line.lower()
        owns_line = any(marker in lowered for marker in markers)
        opposite_line = any(marker in lowered for marker in opposite)

        if owns_line:
            if current:
                blocks.append("\n".join(current))
            current = [line]
            continue

        if opposite_line:
            if current:
                blocks.append("\n".join(current))
                current = None
            continue

        if current is not None and line:
            current.append(line)

    if current:
        blocks.append("\n".join(current))
    return blocks


def _party_is_legal_entity(text: str, markers: tuple[str, ...]) -> bool:
    for segment in _party_segments(text, markers):
        lowered = f" {segment.lower()} "
        if any(marker in lowered for marker in _LEGAL_ENTITY_MARKERS):
            return True
    windows = "\n".join(_windows(text, markers, 180)).lower()
    return any(marker in windows for marker in _LEGAL_ENTITY_MARKERS)


def _has_role_bound_name(text: str, markers: tuple[str, ...]) -> bool:
    for window in _windows(text, markers, 120):
        for candidate in _NAME_RE.findall(window):
            lowered = candidate.lower()
            if any(word in lowered for word in ("сообщения пользователя", "материалы дела", "важные факты", "гражданский кодекс")):
                continue
            return True
    return False


def _has_role_bound_legal_name(text: str, markers: tuple[str, ...]) -> bool:
    """Require the organisation marker and a non-empty name in the same party segment/window."""
    prefixes = (
        r"\bТОО\b", r"\bАО\b", r"\bРГП\b", r"\bРГУ\b", r"\bКГУ\b", r"\bКГП\b", r"\bИП\b",
        r"акционерное\s+общество", r"товарищество\s+с\s+ограниченной\s+ответственностью",
    )
    org_re = re.compile(
        rf"(?:{'|'.join(prefixes)})\s*(?:[«\"“][^»\"”]{{2,}}[»\"”]|[А-ЯЁA-Z0-9][^,;\n]{{2,}})",
        re.IGNORECASE,
    )
    for segment in _party_segments(text, markers):
        if org_re.search(segment):
            return True
    for window in _windows(text, markers, 140):
        if org_re.search(window):
            return True
    return False


def _has_role_bound_identifier(text: str, markers: tuple[str, ...], label: str) -> bool:
    label_re = re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE)
    for segment in _party_segments(text, markers):
        if label_re.search(segment) and _TWELVE_DIGIT_RE.search(segment):
            return True
    for window in _windows(text, markers, 180):
        if label_re.search(window) and _TWELVE_DIGIT_RE.search(window):
            return True
    return False


def _has_role_bound_iin(text: str, markers: tuple[str, ...]) -> bool:
    return _has_role_bound_identifier(text, markers, "иин")


def _has_role_bound_bin(text: str, markers: tuple[str, ...]) -> bool:
    return _has_role_bound_identifier(text, markers, "бин")


def _looks_like_address(segment: str) -> bool:
    lowered = f" {segment.lower()} "
    return any(token in lowered for token in _ADDRESS_MARKERS)


def _has_role_bound_address(text: str, markers: tuple[str, ...]) -> bool:
    claimant = markers == _CLAIMANT_MARKERS

    # First accept the compact one-line form.
    for segment in _segments(text):
        lowered = segment.lower()
        if any(marker in lowered for marker in markers) and _looks_like_address(segment):
            return True

    # Then accept the normal Telegram form where the address is on a following
    # line, but only inside this party's block.  The block terminates as soon as
    # the opposite party begins, preventing cross-party address leakage.
    for block in _party_blocks(text, markers):
        if _looks_like_address(block):
            return True

    lowered = text.lower()
    if claimant:
        patterns = (
            r"\bмой\s+адрес\b",
            r"\bадрес\s+истц[а-яё]*\b",
            r"\bместо\s+жительства\s+истц[а-яё]*\b",
            r"\bместо\s+нахождения\s+истц[а-яё]*\b",
            r"\bя\s+проживаю\b",
            r"\bя\s+живу\b",
            r"\bпроживаю\s+по\s+адресу\b",
        )
    else:
        patterns = (
            r"\bадрес\s+ответчик[а-яё]*\b",
            r"\bместо\s+жительства\s+ответчик[а-яё]*\b",
            r"\bместо\s+нахождения\s+ответчик[а-яё]*\b",
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

    claimant_is_legal_entity = _party_is_legal_entity(text, _CLAIMANT_MARKERS)
    defendant_is_legal_entity = _party_is_legal_entity(text, _DEFENDANT_MARKERS)
    claimant_windows = "\n".join(_windows(text, _CLAIMANT_MARKERS, 260)).lower()

    missing: list[str] = []

    if claimant_is_legal_entity:
        if not _has_role_bound_legal_name(text, _CLAIMANT_MARKERS):
            missing.append("полное наименование истца")
        if not _has_role_bound_bin(text, _CLAIMANT_MARKERS):
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

    if defendant_is_legal_entity:
        if not _has_role_bound_legal_name(text, _DEFENDANT_MARKERS):
            missing.append("полное наименование ответчика")
        if not _has_role_bound_bin(text, _DEFENDANT_MARKERS):
            missing.append("БИН ответчика")
        if not _has_role_bound_address(text, _DEFENDANT_MARKERS):
            missing.append("место нахождения ответчика")
    else:
        if not _has_role_bound_name(text, _DEFENDANT_MARKERS):
            missing.append("ФИО ответчика полностью")
        if not _has_role_bound_address(text, _DEFENDANT_MARKERS):
            missing.append("адрес места жительства ответчика")

    return ClaimPreflight(tuple(dict.fromkeys(missing)))
