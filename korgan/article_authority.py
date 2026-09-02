"""Номер статьи в документе — только тот, что подтверждён lookup-ом.

Что закрывает модуль
--------------------
Проверка ссылок в KORGAN уже была, но охватывала не то и не всё.

``claim_filing_accuracy._ground_legal_basis`` перепривязывает к корпусу только
раздел «Правовое обоснование». Номер статьи, оказавшийся в фактической части,
в просительной, в заголовке или в разделе о подсудности, не проверялся вовсе.

``citation_audit.extract_references`` не видит перечисления: в строке
«ст. 178, 180 ГК РК» он находит 178 и не находит 180. Непроверенный номер
проходил в документ, потому что его никто не искал.

Здесь обе дыры закрыты, и правило одно: напечатанный номер статьи обязан иметь
``LookupResult`` с ``verified=True``. Неподтверждённый номер снимается, а на
его месте остаётся общая формулировка об отрасли законодательства — предложение
сохраняет смысл, но перестаёт утверждать конкретную норму.

Почему снимается, а не помечается
---------------------------------
Прежний аудит выпускал непроверенный номер с видимой пометкой о необходимости
сверки. В судебном тексте такая пометка читается как часть позиции истца, а
номер всё равно напечатан: суд прочитает его как утверждение. Пометка защищает
KORGAN, но не документ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from korgan.article_lookup import LookupFn, LookupResult, lookup_article
from korgan.article_lookup import _REFERRAL_RE as _REFERRAL_STATEMENT_RE
from korgan.provision_check import paraphrase_defects

AUTHORITY_NOTE_PREFIX = "Ссылка на норму: "

# Отрасль законодательства для общей формулировки. Замена сохраняет предложение
# и снимает из него только утверждение о конкретной норме.
_GENERIC_BY_CODE: dict[str, str] = {
    "ГК РК": "гражданского законодательства Республики Казахстан",
    "ГПК РК": "гражданского процессуального законодательства Республики Казахстан",
    "НК РК": "налогового законодательства Республики Казахстан",
    "ТК РК": "трудового законодательства Республики Казахстан",
    "ЗПП РК": "законодательства Республики Казахстан о защите прав потребителей",
    "КАС РК": "административного процедурно-процессуального законодательства Республики Казахстан",
    "КоАП РК": "законодательства Республики Казахстан об административных правонарушениях",
}

# Предложные конструкции, в которых ссылку можно заменить общей формулировкой,
# не сломав согласование. Ключ — предлог, значение — форма слова «нормы».
#
# Вне этих конструкций замена не делается: «Ст. 180 ГК РК предусматривает» при
# механической подстановке даёт «Нормы законодательства предусматривает», и
# документ выглядит собранным автоматом. Такая строка снимается целиком.
_PREPOSITIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"в\s+соответствии\s+с(?:о)?\s*$", re.IGNORECASE), "нормами"),
    (re.compile(r"согласно\s*$", re.IGNORECASE), "нормам"),
    (re.compile(r"(?:на\s+основании|в\s+силу|в\s+порядке|исходя\s+из)\s*$", re.IGNORECASE), "норм"),
    (re.compile(r"руководствуясь\s*$", re.IGNORECASE), "нормами"),
    (re.compile(r"(?:^|[\s(,])по\s*$", re.IGNORECASE), "нормам"),
    (re.compile(r"предусмотренн\w*\s*$", re.IGNORECASE), "нормами"),
)

_ACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс", re.IGNORECASE), "ГПК РК"),
    (re.compile(r"гк\s*рк|гражданск\w*\s+кодекс", re.IGNORECASE), "ГК РК"),
    (re.compile(r"нк\s*рк|налогов\w*\s+кодекс", re.IGNORECASE), "НК РК"),
    (re.compile(r"тк\s*рк|трудов\w*\s+кодекс", re.IGNORECASE), "ТК РК"),
    (re.compile(r"кас\s*рк|административн\w*\s+процедурн", re.IGNORECASE), "КАС РК"),
    (re.compile(r"коап\s*рк|об\s+административных\s+правонарушениях", re.IGNORECASE), "КоАП РК"),
    (
        re.compile(r"зпп\s*рк|о\s+защите\s+прав\s+потребител", re.IGNORECASE),
        "ЗПП РК",
    ),
)

# Ссылка целиком, вместе с перечислением: «ст. 178, 180 и 183 ГК РК»,
# «пунктом 1 статьи 439 ГК РК», «частью 4 статьи 166 ГПК РК».
#
# Перечисление разбирается отдельной группой, потому что прежний разбор
# останавливался на первом номере и делал остальные невидимыми для проверки.
_CITATION_RE = re.compile(
    r"(?:(?P<part_kind>част[ьияею]\w*|ч\.|подпункт\w*|пп\.|пункт\w*|п\.)\s*(?P<part>\d+(?:\.\d+)*)\s*)?"
    r"(?P<article_kind>стать[ияеёюям]\w*|ст\.)\s*"
    r"(?P<numbers>\d+(?:-\d+)?(?:\s*(?:,|и)\s*\d+(?:-\d+)?)*)"
    r"\s*(?P<act>гк\s*рк|гпк\s*рк|нк\s*рк|тк\s*рк|зпп\s*рк|кас\s*рк|коап\s*рк|"
    r"гражданск\w*(?:\s+процессуальн\w*)?\s+кодекс\w*(?:\s+рк|\s+республики\s+казахстан)?"
    r"(?:\s*\([^)]{0,40}\))?|"
    r"налогов\w*\s+кодекс\w*(?:\s+рк|\s+республики\s+казахстан)?|"
    r"трудов\w*\s+кодекс\w*(?:\s+рк|\s+республики\s+казахстан)?|"
    r"закона\s+рк\s*«о\s+защите\s+прав\s+потребителей»)",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(r"\d+(?:-\d+)?")

# Служебная пометка продукта: «[ТРЕБУЕТ ПРОВЕРКИ: ... статья 353 ГК РК не
# подтверждена ...]». Номер статьи внутри неё — не утверждение о праве, а
# описание того, чего не хватило проверке. Читать его как ссылку значит снимать
# строку за сообщение о том, что норма не подтверждена, — то есть за
# правильное поведение предыдущего слоя.
#
# Сами эти пометки в судебном тексте нежелательны, но их снятие — предмет
# post-generation линтера, а не проверки ссылок.
_SERVICE_MARKER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ|НАҚТЫЛАУ|ТЕКСЕРУ|NEEDS)[^\]]*\]",
    re.IGNORECASE,
)


def _service_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _SERVICE_MARKER_RE.finditer(text or "")]


def _inside_service_marker(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


@dataclass(frozen=True, slots=True)
class CitationSite:
    """Одно упоминание нормы в тексте: где стоит и что называет."""

    field_name: str
    index: int
    raw: str
    code: str
    articles: tuple[str, ...]
    part: str


@dataclass(frozen=True, slots=True)
class CitationDecision:
    """Что сделано с одним номером статьи и на каком основании."""

    code: str
    article: str
    part: str
    printed: bool
    lookup: LookupResult
    field_name: str
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "article": self.article,
            "part": self.part,
            "printed": self.printed,
            "field": self.field_name,
            "detail": self.detail,
            "lookup": self.lookup.as_dict(),
        }


@dataclass(slots=True)
class ArticleAuthorityReport:
    decisions: list[CitationDecision] = field(default_factory=list)
    lawyer_notes: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)

    @property
    def printed(self) -> list[CitationDecision]:
        return [item for item in self.decisions if item.printed]

    @property
    def suppressed(self) -> list[CitationDecision]:
        return [item for item in self.decisions if not item.printed]

    def traceability(self) -> list[dict[str, object]]:
        """Связь «напечатанный номер → source_hash подтверждающей записи»."""
        return [
            {
                "reference": decision.lookup.label,
                "code": decision.code,
                "article": decision.article,
                "part": decision.part,
                "source_hash": decision.lookup.source_hash,
                "source_url": decision.lookup.source_url,
                "edition_date": decision.lookup.edition_date,
                "field": decision.field_name,
            }
            for decision in self.printed
        ]

    def as_dict(self) -> dict[str, object]:
        return {
            "printed": [item.as_dict() for item in self.printed],
            "suppressed": [item.as_dict() for item in self.suppressed],
            "traceability": self.traceability(),
            "lawyer_notes": list(self.lawyer_notes),
        }


def _detect_code(text: str) -> str:
    for pattern, code in _ACT_PATTERNS:
        if pattern.search(text or ""):
            return code
    return ""


def find_citations(text: str, *, field_name: str = "", index: int = 0) -> list[CitationSite]:
    """Найти все упоминания норм, включая перечисления.

    Перечисление разбирается на отдельные статьи намеренно: «ст. 178, 180 ГК РК»
    содержит два самостоятельных утверждения о праве, и подтверждение одного не
    подтверждает другое.
    """
    sites: list[CitationSite] = []
    spans = _service_spans(text)
    for match in _CITATION_RE.finditer(text or ""):
        if _inside_service_marker(spans, match.start(), match.end()):
            continue
        code = _detect_code(match.group("act"))
        if not code:
            continue
        numbers = tuple(dict.fromkeys(_NUMBER_RE.findall(match.group("numbers"))))
        if not numbers:
            continue
        part = (match.group("part") or "").strip() if len(numbers) == 1 else ""
        sites.append(
            CitationSite(
                field_name=field_name,
                index=index,
                raw=match.group(0),
                code=code,
                articles=numbers,
                part=part,
            )
        )
    return sites


def _generic_replacement(text: str, start: int, code: str) -> str | None:
    """Общая формулировка вместо ссылки, согласованная с предлогом перед ней."""
    branch = _GENERIC_BY_CODE.get(code)
    if not branch:
        return None
    before = text[:start]
    for pattern, form in _PREPOSITIONS:
        if pattern.search(before):
            return f"{form} {branch}"
    return None


def _normalize_prepositions(text: str) -> str:
    """Починить «со» перед согласной после замены ссылки.

    «В соответствии со ст. 180» после подстановки давало «со нормами». Предлог
    выбирается по первой букве следующего слова, и после замены слово другое.
    """
    return re.sub(r"\bсо(\s+нормам)", r"с\1", text, flags=re.IGNORECASE)


#: Поля черновика, в которых номер статьи вообще может оказаться.
_TEXT_FIELDS = ("title", "price_of_claim", "state_duty", "jurisdiction_reason",
                "limitation_period", "pretrial_compliance", "reconciliation_measures",
                "late_interest")
_LIST_FIELDS = ("facts", "legal_basis", "requests", "attachments", "calculation",
                "motions", "anticipated_defenses")


def _statement_supported(
    statement: str, result: LookupResult, *, single_reference: bool
) -> tuple[bool, str]:
    """Подтверждает ли текст нормы то, что о ней утверждает документ.

    Проверка отдельная от существования статьи, потому что это разные ошибки.
    Статья 458 ГК РК существует и подтверждена корпусом, но она отсылочная: к
    поставке применяются правила о купле-продаже. Обязанность покупателя
    оплатить товар создаёт та норма, к которой отсылка ведёт, а не сама отсылка.
    Напечатать 458 как основание требования об оплате — назвать норму, которой
    этой обязанности в тексте нет.

    Правило об отсылке действует всегда. Сверка пересказа — только для
    одиночной ссылки: в перечислении «статьи 178, 183» каждая норма покрывает
    свою часть утверждения, и требовать от каждой пересказа всего предложения
    значит снимать верные ссылки за то, что предложение говорит не только о них.
    """
    if not result.text:
        return True, ""

    if result.is_referral and not _REFERRAL_STATEMENT_RE.search(statement):
        return False, (
            f"{result.label} является отсылочной нормой и сама правила не устанавливает; "
            "основанием требования должна быть норма, к которой отсылка ведёт"
        )

    if not single_reference:
        return True, ""

    drift = paraphrase_defects(statement, result.text)
    if drift:
        return False, "; ".join(drift[:2])
    return True, ""


def enforce_article_authority(
    draft: object,
    *,
    lookup: LookupFn = lookup_article,
) -> ArticleAuthorityReport:
    """Оставить в документе только подтверждённые номера статей.

    Обход идёт по всем текстовым полям черновика, а не по одному разделу
    правового обоснования: суд читает документ целиком, и номер статьи в
    фактической части утверждает право ровно так же, как в мотивировочной.
    """
    report = ArticleAuthorityReport()
    cache: dict[tuple[str, str, str], LookupResult] = {}

    def resolve(code: str, article: str, part: str) -> LookupResult:
        key = (code, article, part)
        if key not in cache:
            cache[key] = lookup(code, article, part)
        return cache[key]

    def rewrite(value: str, field_name: str, index: int) -> str | None:
        """Новый текст строки, либо None — если строку нужно снять целиком."""
        sites = find_citations(value, field_name=field_name, index=index)
        if not sites:
            return value

        result_text = value
        spans = _service_spans(value)
        # Замены идут справа налево: позиции слева остаются валидными.
        for match in reversed(list(_CITATION_RE.finditer(value))):
            if _inside_service_marker(spans, match.start(), match.end()):
                continue
            code = _detect_code(match.group("act"))
            if not code:
                continue
            numbers = list(dict.fromkeys(_NUMBER_RE.findall(match.group("numbers"))))
            if not numbers:
                continue
            part = (match.group("part") or "").strip() if len(numbers) == 1 else ""

            verified: list[tuple[str, LookupResult]] = []
            rejected: list[tuple[str, LookupResult, str]] = []
            for article in numbers:
                result = resolve(code, article, part)
                if not result.verified:
                    rejected.append((article, result, result.reason))
                    continue
                supported, why = _statement_supported(
                    value, result, single_reference=len(numbers) == 1
                )
                if not supported:
                    rejected.append((article, result, why))
                    continue
                verified.append((article, result))

            for article, result in verified:
                report.decisions.append(
                    CitationDecision(
                        code=code,
                        article=article,
                        part=part,
                        printed=True,
                        lookup=result,
                        field_name=field_name,
                        detail=f"подтверждено: {result.origin or 'source-bound проверка'}",
                    )
                )
            for article, result, why in rejected:
                report.decisions.append(
                    CitationDecision(
                        code=code,
                        article=article,
                        part=part,
                        printed=False,
                        lookup=result,
                        field_name=field_name,
                        detail=why,
                    )
                )
                note = f"{AUTHORITY_NOTE_PREFIX}{result.label} не выпущена в документ — {why}"
                if note not in report.lawyer_notes:
                    report.lawyer_notes.append(note)

            if not rejected:
                continue

            if verified:
                # Часть перечисления подтверждена: печатаем подтверждённые
                # номера и убираем остальные. Ссылка остаётся ссылкой.
                kept = ", ".join(article for article, _ in verified)
                prefix = match.group(0)[: match.start("numbers") - match.start()]
                suffix = match.group(0)[match.end("numbers") - match.start():]
                replacement = f"{prefix}{kept}{suffix}"
            else:
                replacement = _generic_replacement(result_text, match.start(), code) or ""
                if not replacement:
                    return None
            result_text = result_text[: match.start()] + replacement + result_text[match.end():]

        return _normalize_prepositions(" ".join(result_text.split()))

    for name in _TEXT_FIELDS:
        value = str(getattr(draft, name, "") or "")
        if not value:
            continue
        updated = rewrite(value, name, 0)
        if updated is None:
            report.removed_lines.append(f"{name}: {value}")
            setattr(draft, name, "")
        elif updated != value:
            setattr(draft, name, updated)

    for name in _LIST_FIELDS:
        values = getattr(draft, name, None)
        if not isinstance(values, list):
            continue
        kept: list[str] = []
        for index, raw in enumerate(values):
            value = str(raw)
            updated = rewrite(value, name, index)
            if updated is None:
                report.removed_lines.append(f"{name}[{index}]: {value}")
                continue
            kept.append(updated)
        setattr(draft, name, kept)

    for line in report.removed_lines:
        note = (
            f"{AUTHORITY_NOTE_PREFIX}строка снята целиком, поскольку без номера статьи "
            f"она теряет смысл: {line}"
        )
        if note not in report.lawyer_notes:
            report.lawyer_notes.append(note)

    return report
