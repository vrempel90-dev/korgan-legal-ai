"""Что действительно нужно спросить до генерации, а что помечается в документе.

Раньше первый шаг работал как анкета: `claim_preflight` возвращал список
недостающих полей, и любое из них — дата рождения истца, ИИН, банковские
реквизиты — останавливало подготовку иска. Клиент описывал дело один раз, а
потом проходил три-четыре раунда «пришлите недостающее», прежде чем впервые
видел черновик.

Между тем сам проект уже знает, как поступать с неизвестным реквизитом: он
пишет `[ТРЕБУЕТ УТОЧНЕНИЯ: ...]` — ровно так работают шаблоны договоров. Это и
есть правильное поведение по умолчанию, и здесь оно распространяется на иски.

Поэтому пробелы делятся на два класса:

* **критичные** — без них документ не имеет смысла: кто истец, кто ответчик, в
  чём требование и его сумма, если требование денежное. Их спрашивают ОДИН раз
  и все сразу, одним сообщением;
* **формальные** — нужны для подачи, но не для смысла: дата рождения, ИИН/БИН,
  адреса сторон, банковские реквизиты, точное наименование суда, госпошлина.
  Они не блокируют ничего: документ выдаётся с плейсхолдером на месте каждого,
  и клиент заполняет их сам, разом, по готовому черновику.

Классификация детерминированная и живёт отдельно от модели: правило, которое
находится в промпте, применяется настолько часто, насколько модель о нём
вспомнит.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from korgan.claim_preflight import (
    _CLAIMANT_MARKERS,
    _DEFENDANT_MARKERS,
    _has_role_bound_name,
    inspect_claim_context,
)
from korgan.legal_types import ClaimDraft

PLACEHOLDER = "[ТРЕБУЕТ УТОЧНЕНИЯ: {}]"

# Суть требования и его цена — не «поля анкеты», а условие осмысленности иска.
RELIEF_GAP = "в чём состоит требование к ответчику (что просить у суда)"
AMOUNT_GAP = "сумма требования"

_DATE_RE = re.compile(r"(?<!\d)(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?!\d)")
_IIN_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_IBAN_RE = re.compile(r"\bKZ[0-9A-Z]{16,18}\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?<!\d)\d[\d\s  .,]{2,}\s*(?:тенге|тг\b|₸|kzt)", re.IGNORECASE)

_ADDRESS_TOKENS = (
    "ул.", "улица", "мкр", "микрорайон", "проспект", "пр-т", "д.", "дом", "кв.",
    "квартира", "г.", "город", "село", "район", "область", "шоссе", "переулок",
)
_BANK_TOKENS = ("iban", "банк", "бик", "счет", "счёт", "kaspi", "halyk")

# Требование, сформулированное клиентом словами.
_RELIEF_PATTERNS = (
    r"\bвзыска\w*\b",
    r"\bвернут\w*\b|\bвозврат\w*\b|\bвозврати\w*\b|\bверни\w*\b",
    r"\bрасторг\w*\b",
    r"\bпризна\w*\b\s+\w*\s*(?:недействительн|незаконн|прав\w*)",
    r"\bобяза\w*\b\s+\w*\s*(?:ответчик|подрядчик|исполнител|продавц|застройщик)",
    r"\bкомпенсир\w*\b|\bвозмест\w*\b",
    r"\bистреб\w*\b|\bвыселит\w*\b|\bотмен\w*\b",
    r"\bтребую\b|\bпрошу\b|\bхочу\s+(?:вернуть|взыскать|отсудить|получить)\b",
    r"\bподготов\w*\b.{0,40}\bиск\w*\b|\bиск\w*\b.{0,40}\bо\s+взыскани\w*\b",
)

# Нарушение, из которого требование выводится без домысла.
_BREACH_PATTERNS = (
    r"\bне\s+(?:вернул\w*|возвратил\w*|выполнил\w*|исполнил\w*|поставил\w*|оплатил\w*|заплатил\w*|передал\w*|сделал\w*|отдал\w*)\b",
    r"\bне\s+был\w*\s+(?:выполнен|исполнен|поставлен|возвращен|возвращён)\w*\b",
    r"\bнаруш\w*\b",
    r"\bпросроч\w*\b",
    r"\bуклоня\w*\b|\bотказыва\w*\b",
    r"\bнедостатк\w*\b|\bбрак\b|\bнекачественн\w*\b",
    r"\bзадолженност\w*\b|\bдолг\w*\b",
)


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


def _looks_like_address(value: str) -> bool:
    lowered = f" {value.lower()} "
    if not any(token in lowered for token in _ADDRESS_TOKENS):
        return False
    return bool(re.search(r"\d", value)) or "," in value


def _looks_like_bank(value: str) -> bool:
    lowered = value.lower()
    return bool(_IBAN_RE.search(value)) or any(token in lowered for token in _BANK_TOKENS)


@dataclass(frozen=True, slots=True)
class FormalField:
    """Формальный реквизит: как его опознать в проекте и чем заместить."""

    label: str      # ровно как его называет claim_preflight в `missing`
    target: str     # поле ClaimDraft, в которое пишется плейсхолдер
    prefix: str     # подпись строки в документе
    kind: str       # date | iin | address | bank


FORMAL_FIELDS: tuple[FormalField, ...] = (
    # Стороны критичны и обычно спрашиваются, но после единственного вопроса
    # даже они становятся пометкой: второго раунда не бывает.
    FormalField("ФИО истца полностью", "claimant", "Истец", "name"),
    FormalField("полное наименование истца", "claimant", "Истец", "name"),
    FormalField("ФИО ответчика полностью", "defendant", "Ответчик", "name"),
    FormalField("дата рождения истца", "claimant", "Дата рождения", "date"),
    FormalField("ИИН истца", "claimant", "ИИН", "iin"),
    FormalField("БИН истца", "claimant", "БИН", "iin"),
    FormalField("адрес места жительства истца", "claimant", "Адрес", "address"),
    FormalField("место нахождения истца", "claimant", "Место нахождения", "address"),
    FormalField("банковские реквизиты истца", "claimant", "Банковские реквизиты", "bank"),
    FormalField("адрес места жительства ответчика", "defendant", "Адрес", "address"),
)

FORMAL_BY_LABEL: dict[str, FormalField] = {item.label: item for item in FORMAL_FIELDS}

# Всё, что claim_preflight умеет запрашивать и что не перечислено выше, —
# критично: это идентификация сторон, без которой иск ни к кому не обращён.
_CRITICAL_LABELS: frozenset[str] = frozenset(
    {
        "ФИО истца полностью",
        "полное наименование истца",
        "ФИО ответчика полностью",
        "описание обстоятельств дела или материалы",
    }
)

# Метки остаются каноническими — их читает korgan.field_intake, разбирая ответ.
# Пояснение живёт отдельно, чтобы вопрос был человеческим, а разбор — точным.
_CRITICAL_PROMPTS: dict[str, str] = {
    "ФИО истца полностью": "кто истец — ваши фамилия, имя и отчество полностью",
    "полное наименование истца": "кто истец — полное наименование организации",
    "ФИО ответчика полностью": (
        "кто ответчик — фамилия, имя, отчество либо полное наименование организации"
    ),
    "описание обстоятельств дела или материалы": "что произошло — опишите ситуацию своими словами",
    RELIEF_GAP: RELIEF_GAP,
    AMOUNT_GAP: "сумма требования — сколько именно вы просите взыскать",
}

# Клиент описывает дело от первого лица: «я, Иванов Иван Иванович, ...». Роль
# «истец» он при этом не пишет — она следует из того, что он обращается за иском.
_FIRST_PERSON_NAME_RE = re.compile(
    r"(?:^|[.\n]\s*)(?:я|мною)\s*,?\s+(?P<name>[А-ЯЁ][а-яё'’-]+(?:\s+[А-ЯЁ][а-яё'’-]+){1,2})\b"
    r"|(?:меня\s+зовут|моё\s+имя|мое\s+имя|фио|от\s+имени)\s*[:—-]?\s*"
    r"(?P<named>[А-ЯЁ][а-яё'’-]+(?:\s+[А-ЯЁ][а-яё'’-]+){1,2})\b",
    re.IGNORECASE | re.MULTILINE,
)

# Роль ответчика в свободном рассказе тоже называется не словом «ответчик».
_COUNTERPARTY_MARKERS: tuple[str, ...] = _DEFENDANT_MARKERS + (
    "подрядчик", "исполнитель", "продавец", "поставщик", "арендатор",
    "наймодатель", "арендодатель", "работодатель", "застройщик", "страховщик",
    "покупатель", "мастер", "ип ", "тоо ", "ао ",
)


def _claimant_named(text: str) -> bool:
    if _has_role_bound_name(text, _CLAIMANT_MARKERS):
        return True
    match = _FIRST_PERSON_NAME_RE.search(text)
    return bool(match and (match.group("name") or match.group("named")))


def _defendant_named(text: str) -> bool:
    return _has_role_bound_name(text, _COUNTERPARTY_MARKERS)


@dataclass(frozen=True, slots=True)
class ClaimGaps:
    """Пробелы в материалах дела, разложенные по последствиям."""

    critical: tuple[str, ...] = ()
    formal: tuple[str, ...] = ()

    @property
    def blocks_drafting(self) -> bool:
        """Только критичный пробел останавливает подготовку документа."""
        return bool(self.critical)

    def after_the_single_question(self) -> "ClaimGaps":
        """Пробелы после того, как единственный вопрос уже задан и отвечен.

        Уточняющий вопрос по договорённости ровно один. Всё, что не удалось
        получить с него, перестаёт блокировать документ и уходит в пометки —
        иначе «один вопрос» незаметно превращается в тот же квест по полям.
        """
        return ClaimGaps((), tuple(dict.fromkeys([*self.critical, *self.formal])))

    def single_question(self) -> str:
        """Один вопрос по всем критичным пробелам сразу — не серия раундов."""
        items = "\n".join(f"• {_CRITICAL_PROMPTS.get(item, item)}" for item in self.critical)
        return (
            "📋 Чтобы документ вообще имел смысл, не хватает главного:\n\n"
            f"{items}\n\n"
            "Ответьте одним сообщением — этого достаточно. Всё остальное "
            "(дата рождения, ИИН, адреса, банковские реквизиты, наименование суда, "
            "госпошлина) я не спрашиваю: документ придёт сразу, а на месте этих "
            "данных будут пометки [ТРЕБУЕТ УТОЧНЕНИЯ: ...], которые вы заполните "
            "в готовом файле."
        )


def _has_money(text: str) -> bool:
    return bool(_MONEY_RE.search(text))


def _is_monetary_case(text: str) -> bool:
    """Денежное ли требование — только тогда сумма становится критичной."""
    return _has(
        text,
        (
            r"\bвзыска\w*\b",
            r"\bдолг\w*\b|\bзадолженност\w*\b",
            r"\bпредоплат\w*\b|\bаванс\w*\b|\bпредварительн\w*\s+оплат\w*\b",
            r"\bоплат\w*\b|\bуплат\w*\b|\bденьг\w*\b|\bденег\b|\bсумм\w*\b",
            r"\bтенге\b|\bтг\b|₸",
            r"\bубытк\w*\b|\bущерб\w*\b|\bнеустойк\w*\b",
        ),
    )


def inspect_claim_gaps(case_context: str) -> ClaimGaps:
    """Разложить пробелы материалов на «спросить» и «пометить в документе»."""
    text = (case_context or "").strip()
    if not text:
        return ClaimGaps(critical=("описание обстоятельств дела или материалы",))

    preflight = inspect_claim_context(text)
    formal: list[str] = [item for item in preflight.missing if item not in _CRITICAL_LABELS]
    critical: list[str] = []

    # Идентификация сторон проверяется здесь, а не переносится из preflight:
    # preflight ищет имя рядом со словом «истец», а клиент пишет «я, Иванов И.И.»
    # и «подрядчик — Петров П.П.». Отсутствие ярлыка роли — не отсутствие данных.
    if not _claimant_named(text):
        entity = "полное наименование истца" if "полное наименование истца" in preflight.missing else None
        critical.append(entity or "ФИО истца полностью")
    if not _defendant_named(text):
        critical.append("ФИО ответчика полностью")

    # Требование выводится либо из прямой формулировки, либо из описанного
    # нарушения. Требовать и то и другое означало бы вернуть анкету.
    if not _has(text, _RELIEF_PATTERNS) and not _has(text, _BREACH_PATTERNS):
        critical.append(RELIEF_GAP)
    elif _is_monetary_case(text) and not _has_money(text):
        critical.append(AMOUNT_GAP)

    return ClaimGaps(tuple(dict.fromkeys(critical)), tuple(dict.fromkeys(formal)))


_NAME_RE = re.compile(r"[А-ЯЁ][а-яё'’-]+(?:\s+[А-ЯЁ][а-яё'’-]+){1,2}")
_ENTITY_RE = re.compile(r"\b(?:ТОО|АО|ИП|ЖК|КСК|ОО)\b", re.IGNORECASE)


def _party_has(lines: list[str], field: FormalField) -> bool:
    """Уже ли в реквизитах стороны есть значение этого вида."""
    for line in lines:
        value = str(line)
        if field.kind == "name":
            # Имя стороны — единственное, что рендерится без подписи, поэтому
            # ищется по форме значения, а не по префиксу строки.
            if "[ТРЕБУЕТ" not in value.upper() and (
                _NAME_RE.search(value) or _ENTITY_RE.search(value)
            ):
                return True
            continue
        if field.prefix.lower() in value.lower() and "[ТРЕБУЕТ" not in value.upper():
            return True
        if field.kind == "date" and _DATE_RE.search(value):
            return True
        if field.kind == "iin" and _IIN_RE.search(value):
            return True
        if field.kind == "address" and _looks_like_address(value):
            return True
        if field.kind == "bank" and _looks_like_bank(value):
            return True
    return False


def _already_marked(lines: list[str], field: FormalField) -> bool:
    needle = field.label.lower()
    return any(needle in str(line).lower() and "[ТРЕБУЕТ" in str(line).upper() for line in lines)


def apply_formal_placeholders(draft: ClaimDraft, gaps: ClaimGaps) -> list[str]:
    """Заместить формальные пробелы пометками прямо в проекте.

    Возвращает список добавленных пометок — их же показывают клиенту, чтобы он
    заполнил всё разом в готовом файле, а не отвечал на вопросы по одному.
    """
    added: list[str] = []

    for label in gaps.formal:
        field = FORMAL_BY_LABEL.get(label)
        if field is None:
            continue
        lines = list(getattr(draft, field.target, []) or [])
        if _party_has(lines, field) or _already_marked(lines, field):
            continue
        lines.append(f"{field.prefix}: {PLACEHOLDER.format(field.label)}")
        setattr(draft, field.target, lines)
        added.append(field.label)

    # Пустой блок стороны — тоже пробел, и он тоже помечается, а не блокирует.
    for attribute, label in (("claimant", "данные истца"), ("defendant", "данные ответчика")):
        values = [item for item in (getattr(draft, attribute, []) or []) if str(item).strip()]
        if not values:
            setattr(draft, attribute, [PLACEHOLDER.format(label)])
            added.append(label)

    if not (draft.court or "").strip():
        draft.court = PLACEHOLDER.format("точное наименование суда")
        added.append("точное наименование суда")

    if not (draft.price_of_claim or "").strip():
        draft.price_of_claim = PLACEHOLDER.format("цена иска")
        added.append("цена иска")

    return added


def placeholder_notes(added: list[str]) -> list[str]:
    """Одна заметка на все пометки: клиент заполняет их разом в файле."""
    if not added:
        return []
    return [
        "Заполните в файле пометки [ТРЕБУЕТ УТОЧНЕНИЯ: ...] — "
        + ", ".join(dict.fromkeys(added))
        + ". Документ готов к правке: отдельные сведения присылать не нужно."
    ]
