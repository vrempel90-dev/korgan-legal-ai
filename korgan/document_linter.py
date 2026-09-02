"""Детерминированный линтер готового документа. Жёсткий гейт перед выдачей.

Зачем нужен отдельный линтер
----------------------------
Проверки качества в KORGAN распределены по слоям, которые собирают документ:
расчёт следит за числами, проверка ссылок — за нормами, quality gate — за
полнотой. Ни одна из них не смотрит на СОБРАННЫЙ документ целиком, а часть
дефектов возникает именно при сборке: служебная пометка, попавшая из
внутреннего канала в судебное тело; сумма, разошедшаяся с расчётом после
раунда ремонта; ходатайство, просящее суд истребовать у истца документ,
который истец сам приложил.

Линтер запускается после того, как содержание документа сформировано, и до
того, как выдача разрешена. Он ничего не исправляет: нарушение означает, что
неизвестно, какая часть документа верна, а какая устарела. Он также ничего не
маскирует — пометка «предварительный документ» не превращает противоречие в
допустимое.

Модель здесь не используется вообще. Каждое правило — сравнение текста со
структурой или структуры с самой собой.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from korgan.article_authority import find_citations
from korgan.legal_calc import parse_all_amounts_kzt
from korgan import style_guide

#: Единственная разрешённая служебная строка в отрендеренном документе —
#: видимый QA-штамп в шапке. Он адресован клиенту, а не суду, и предусмотрен
#: продуктом; всё остальное служебное в судебном теле — дефект сборки.
QA_WATERMARK_PREFIX = "KORGAN QA STATUS"


class LintStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class LintFinding:
    rule: str
    location: str
    message: str
    suggested_fix: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "location": self.location,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
        }


@dataclass(slots=True)
class LintResult:
    status: LintStatus
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status is LintStatus.BLOCKED

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "findings": [finding.as_dict() for finding in self.findings],
        }

    def summary(self) -> str:
        if not self.blocked:
            return "PASS"
        return "BLOCKED: " + "; ".join(f"{item.rule} @ {item.location}" for item in self.findings)


# --------------------------------------------------------------------------
# Правило 1. Служебные маркеры в судебном теле
# --------------------------------------------------------------------------

_SERVICE_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "verification_notes",
        re.compile(r"verification[_\s]?notes?", re.IGNORECASE),
        "убрать внутреннюю заметку проверки из судебного текста; она относится к каналу QA",
    ),
    (
        "qa_json",
        re.compile(r"(?:QA\s*STATUS|\"critical_errors\"|\"unsupported_legal_claims\"|"
                   r"\"missing_required_fields\"|\{\s*\"[a-z_]+\"\s*:)", re.IGNORECASE),
        "убрать служебную структуру QA из документа",
    ),
    (
        "internal_todo",
        re.compile(r"\bTODO\b|\bFIXME\b|\bXXX\b|дописать\s+позже|уточнить\s+у\s+разработчик", re.IGNORECASE),
        "снять внутреннюю задачу; невыполненная работа не публикуется в судебном тексте",
    ),
    (
        "debug_payload",
        re.compile(r"\bDEBUG\b|\bTRACE\b|Traceback\s*\(|<\s*object\s+at\s+0x|\bNone\b\s*$", re.IGNORECASE),
        "убрать отладочный вывод",
    ),
    (
        "structured_reasoning",
        re.compile(r"(?:^|\n)\s*(?:ШАГ|STEP)\s*\d+\s*[:.]|цепочка\s+рассуждени|chain[_\s]of[_\s]thought",
                   re.IGNORECASE),
        "убрать внутреннее рассуждение; в документ идёт вывод, а не ход мысли",
    ),
    (
        "internal_quality_note",
        re.compile(r"KORGAN\s+QUALITY|SENIOR_PREFLIGHT_SCORE|CLAIM_PIPELINE|"
                   r"Дополнительная\s+процессуальная\s+проверка|Детерминированный\s+расчёт:|"
                   r"Ссылка\s+на\s+норму:", re.IGNORECASE),
        "убрать внутреннюю заметку качества из судебного текста",
    ),
    (
        "repair_marker",
        re.compile(r"NEEDS_VERIFICATION|PRELIMINARY|repair[_\s]round|VERIFIED_COURT|"
                   r"LEGAL_CORRECTION|LEGAL_GROUNDING", re.IGNORECASE),
        "убрать служебный маркер ремонта",
    ),
    (
        "technical_placeholder_name",
        re.compile(r"\b(?:principal_amount|penalty_amount|claim_price|state_duty|total_claim|"
                   r"case_context|draft\.|legal_basis|price_of_claim)\b"),
        "заменить техническое имя поля на нормальную формулировку",
    ),
)


# --------------------------------------------------------------------------
# Правило 2. Незаполненные числовые поля
# --------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{\s*[a-z_]+\s*\}\}", re.IGNORECASE)
_CALCULATION_MARKER_RE = re.compile(r"\[ТРЕБУЕТ\s+РАСЧ[ЁЕ]ТА[^\]]*\]", re.IGNORECASE)
_ENGLISH_PLACEHOLDER_RE = re.compile(r"\bplaceholder\b|<\s*[a-z_]+\s*>", re.IGNORECASE)


# --------------------------------------------------------------------------
# Правило 4. Структурные аномалии
# --------------------------------------------------------------------------

_DEMAND_FROM_CLAIMANT_RE = re.compile(
    r"истребовать|запросить|обязать\s+представить|истреб\w*",
    re.IGNORECASE,
)
_CLAIMANT_MENTION_RE = re.compile(r"\bу\s+истца\b|\bот\s+истца\b|\bистца\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "копия", "копии", "оригинал", "документ", "документы", "договор", "договора",
        "приложение", "приложения", "истца", "истец", "ответчика", "ответчик", "суда",
        "года", "году", "номер", "далее", "также", "иные", "иных",
    }
)
_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.IGNORECASE)

_TOTAL_PHRASE_RE = re.compile(
    r"(?:общая\s+сумма|итого|всего)\s+(?:исковых\s+требований\s+|ко\s+взысканию\s+|"
    r"взыскания\s+|требований\s+)?",
    re.IGNORECASE,
)
_STATE_DUTY_OR_COST_RE = re.compile(
    r"(?:государственн\w*\s+пошлин\w*|госпошлин\w*|судебн\w*\s+(?:расход\w*|издерж\w*)|"
    r"расход\w*\s+на\s+(?:оплат\w*\s+)?представител\w*)",
    re.IGNORECASE,
)


def _significant_words(text: str) -> set[str]:
    return {
        word.lower()
        for word in _WORD_RE.findall(text or "")
        if word.lower() not in _STOPWORDS
    }


def _describes_the_same_document(motion: str, attachment: str) -> bool:
    """Говорят ли ходатайство и приложение об одном документе.

    Сравнение по значимым словам, а не по строке целиком: истец пишет
    «Копия договора поставки № 14/2026 от 02.02.2026» в приложениях и
    «договор поставки № 14/2026» в ходатайстве — это один документ, названный
    двумя способами.
    """
    motion_words = _significant_words(motion)
    attachment_words = _significant_words(attachment)
    if len(attachment_words) < 2:
        return False
    overlap = motion_words & attachment_words
    return len(overlap) >= 2 and len(overlap) / len(attachment_words) >= 0.5


def _body_lines(draft: Any) -> list[tuple[str, str]]:
    """Пары «где — что» по всему судебному телу документа."""
    lines: list[tuple[str, str]] = []
    for name in ("title", "court", "price_of_claim", "state_duty", "jurisdiction_reason",
                 "limitation_period", "pretrial_compliance", "reconciliation_measures",
                 "late_interest"):
        value = str(getattr(draft, name, "") or "").strip()
        if value:
            lines.append((name, value))
    for name in ("claimant", "defendant", "facts", "legal_basis", "requests",
                 "attachments", "calculation", "motions"):
        values = getattr(draft, name, None)
        if isinstance(values, list):
            for index, value in enumerate(values):
                text = str(value).strip()
                if text:
                    lines.append((f"{name}[{index}]", text))
    return lines


def _calculated(result: dict[str, Any], key: str) -> int | None:
    field_data = result.get(key)
    if not isinstance(field_data, dict):
        return None
    if field_data.get("status") != "calculated":
        return None
    value = field_data.get("value")
    return int(value) if isinstance(value, int) else None


def _insufficient_fields(result: dict[str, Any]) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for key in ("principal", "penalty", "claim_price", "state_duty", "total_claim"):
        field_data = result.get(key)
        if isinstance(field_data, dict) and field_data.get("status") == "insufficient_data":
            found.append((key, [str(item) for item in field_data.get("missing", [])]))
    return found


def _check_service_markers(draft: Any) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for location, text in _body_lines(draft):
        if text.startswith(QA_WATERMARK_PREFIX):
            continue
        for rule, pattern, fix in _SERVICE_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    LintFinding(
                        rule=rule,
                        location=location,
                        message=f"в судебном тексте служебный фрагмент «{match.group(0).strip()}»",
                        suggested_fix=fix,
                    )
                )
                break
    return findings


def _check_placeholders(draft: Any) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for location, text in _body_lines(draft):
        for rule, pattern, fix in (
            ("unresolved_placeholder", _PLACEHOLDER_RE,
             "подставить рассчитанное значение либо снять требование целиком"),
            ("unresolved_calculation_marker", _CALCULATION_MARKER_RE,
             "довести расчёт до числа либо оставить поле пустым и вынести дефицит данных юристу"),
            ("technical_placeholder_token", _ENGLISH_PLACEHOLDER_RE,
             "убрать технический плейсхолдер"),
        ):
            match = pattern.search(text)
            if match:
                findings.append(
                    LintFinding(
                        rule=rule,
                        location=location,
                        message=f"незаполненное поле: «{match.group(0)}»",
                        suggested_fix=fix,
                    )
                )
                break
    return findings


def _check_calculation_readiness(draft: Any) -> list[LintFinding]:
    """Дефицит данных — отдельное условие выпуска, а не строка в тексте."""
    result = getattr(draft, "calculation_result", None)
    if not isinstance(result, dict) or not result:
        return []
    findings: list[LintFinding] = []
    for key, missing in _insufficient_fields(result):
        findings.append(
            LintFinding(
                rule="insufficient_calculation_data",
                location=f"calculation_result.{key}",
                message="; ".join(missing) or f"поле {key} не рассчитано",
                suggested_fix=(
                    "запросить у клиента недостающие исходные данные; выпуск документа "
                    "с незаполненным денежным полем не разрешается"
                ),
            )
        )
    return findings


def _check_articles(draft: Any) -> list[LintFinding]:
    """Каждый напечатанный номер статьи обязан иметь verified lookup."""
    authority = getattr(draft, "citation_authority", None)
    trace = []
    if isinstance(authority, dict):
        trace = authority.get("traceability") or []
    verified: set[tuple[str, str]] = {
        (str(row.get("code", "")), str(row.get("article", "")))
        for row in trace
        if isinstance(row, dict)
    }

    findings: list[LintFinding] = []
    for location, text in _body_lines(draft):
        for site in find_citations(text, field_name=location):
            for article in site.articles:
                if (site.code, article) in verified:
                    continue
                findings.append(
                    LintFinding(
                        rule="unverified_article",
                        location=location,
                        message=(
                            f"статья {article} {site.code} напечатана без подтверждённой записи "
                            "корпуса (verified lookup отсутствует)"
                        ),
                        suggested_fix=(
                            "снять номер статьи и оставить общую формулировку об отрасли "
                            "законодательства либо подтвердить норму по официальному источнику"
                        ),
                    )
                )
    return findings


def _check_motions_against_attachments(draft: Any) -> list[LintFinding]:
    """Суд не истребует у истца то, что истец сам приложил."""
    attachments = [str(item) for item in (getattr(draft, "attachments", None) or [])]
    if not attachments:
        return []

    findings: list[LintFinding] = []
    sources = [("motions", getattr(draft, "motions", None) or []),
               ("requests", getattr(draft, "requests", None) or [])]
    for name, values in sources:
        for index, raw in enumerate(values):
            motion = str(raw)
            if not _DEMAND_FROM_CLAIMANT_RE.search(motion):
                continue
            if not _CLAIMANT_MENTION_RE.search(motion):
                continue
            for attachment in attachments:
                if _describes_the_same_document(motion, attachment):
                    findings.append(
                        LintFinding(
                            rule="motion_requests_claimant_own_attachment",
                            location=f"{name}[{index}]",
                            message=(
                                "ходатайство просит суд истребовать у истца документ, уже "
                                f"приложенный самим истцом: «{attachment}»"
                            ),
                            suggested_fix=(
                                "снять ходатайство: документ приобщён к иску; истребование "
                                "имеет смысл только в отношении доказательств у другой стороны"
                            ),
                        )
                    )
                    break
    return findings


def _check_amounts(draft: Any) -> list[LintFinding]:
    """Суммы документа сверяются со структурированным расчётом."""
    result = getattr(draft, "calculation_result", None)
    if not isinstance(result, dict) or not result:
        return []

    findings: list[LintFinding] = []
    claim_price = _calculated(result, "claim_price")
    principal = _calculated(result, "principal")
    penalty = _calculated(result, "penalty")
    total = _calculated(result, "total_claim")

    requests = [str(item) for item in (getattr(draft, "requests", None) or [])]
    prayer_text = "\n".join(requests)

    if claim_price is not None:
        price_in_header = parse_all_amounts_kzt(str(getattr(draft, "price_of_claim", "") or ""))
        if price_in_header and price_in_header[0] != claim_price:
            findings.append(
                LintFinding(
                    rule="claim_price_mismatch",
                    location="price_of_claim",
                    message=(
                        f"цена иска в шапке {price_in_header[0]} расходится с расчётом {claim_price}"
                    ),
                    suggested_fix="привести цену иска к значению структурированного расчёта",
                )
            )

        # Сумма требований обязана сойтись с ценой иска. Судебные расходы и
        # пошлина в цену иска не входят и из сверки исключаются.
        component_total = 0
        for request in requests:
            if _STATE_DUTY_OR_COST_RE.search(request) or _TOTAL_PHRASE_RE.search(request):
                continue
            amounts = parse_all_amounts_kzt(request)
            if amounts:
                component_total += amounts[0]
        if component_total and component_total != claim_price:
            findings.append(
                LintFinding(
                    rule="prayer_total_mismatch",
                    location="requests",
                    message=(
                        f"сумма денежных требований просительной части {component_total} "
                        f"не равна цене иска {claim_price}"
                    ),
                    suggested_fix="пересобрать просительную часть из структурированного расчёта",
                )
            )

    for label, expected in (("principal", principal), ("penalty", penalty)):
        if expected is None:
            continue
        if expected not in parse_all_amounts_kzt(prayer_text):
            findings.append(
                LintFinding(
                    rule="prayer_amount_missing",
                    location="requests",
                    message=f"рассчитанная сумма ({label}) {expected} отсутствует в просительной части",
                    suggested_fix="привести просительную часть к структурированному расчёту",
                )
            )

    if total is not None:
        stated = any(
            _TOTAL_PHRASE_RE.search(request) and total in parse_all_amounts_kzt(request)
            for request in requests
        )
        if not stated:
            findings.append(
                LintFinding(
                    rule="prayer_without_total_amount",
                    location="requests",
                    message=(
                        f"цена иска и денежные требования рассчитаны, но итоговая сумма "
                        f"взыскания {total} в просительной части не названа"
                    ),
                    suggested_fix=(
                        "добавить в просительную часть итоговую строку с общей суммой ко взысканию"
                    ),
                )
            )

    return findings



# --------------------------------------------------------------------------
# STYLE_GUIDE. Правила оформления, формализованные из STYLE_GUIDE.md
# --------------------------------------------------------------------------


def _style_finding(rule_id: str, location: str, message: str) -> LintFinding:
    described = style_guide.rule(rule_id)
    return LintFinding(
        rule=f"style_guide:{rule_id}",
        location=location,
        message=f"{described.title}: {message}",
        suggested_fix=described.fix,
    )


def _check_style_guide(draft: Any, *, case_context: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    findings.extend(_check_article_8_reference(draft))
    findings.extend(_check_court_costs_request(draft))
    findings.extend(_check_venue_rules(draft))
    findings.extend(_check_party_requisites(draft, case_context=case_context))
    findings.extend(_check_structural_sections(draft))
    return findings


def _check_article_8_reference(draft: Any) -> list[LintFinding]:
    """SG-01: вступительная ссылка на статью 8 ГПК РК — только подтверждённая."""
    authority = getattr(draft, "citation_authority", None)
    trace = authority.get("traceability") or [] if isinstance(authority, dict) else []
    verified = any(
        isinstance(row, dict) and str(row.get("code")) == "ГПК РК" and str(row.get("article")) == "8"
        for row in trace
    )
    for location, text in _body_lines(draft):
        if style_guide.mentions_article_8_gpk(text) and not verified:
            return [
                _style_finding(
                    "SG-01",
                    location,
                    "статья 8 ГПК РК названа без подтверждённой записи корпуса",
                )
            ]
    return []


def _check_court_costs_request(draft: Any) -> list[LintFinding]:
    """SG-02: судебные расходы — самостоятельный пункт просительной части."""
    result = getattr(draft, "calculation_result", None)
    if not isinstance(result, dict) or _calculated(result, "state_duty") is None:
        return []
    requests = [str(item) for item in (getattr(draft, "requests", None) or [])]
    if style_guide.has_separate_court_cost_request(requests):
        return []
    return [
        _style_finding(
            "SG-02",
            "requests",
            "госпошлина рассчитана, но отдельного требования о судебных расходах нет",
        )
    ]


def _check_venue_rules(draft: Any) -> list[LintFinding]:
    """SG-03: родовая и территориальная подсудность не смешиваются."""
    findings: list[LintFinding] = []
    for location, text in _body_lines(draft):
        if style_guide.jurisdiction_mixes_venue_rules(text):
            findings.append(
                _style_finding(
                    "SG-03",
                    location,
                    "статьи 27 и 29 ГПК РК названы в одном предложении без разделения "
                    "на родовую и территориальную подсудность",
                )
            )
    return findings


def _check_party_requisites(draft: Any, *, case_context: str) -> list[LintFinding]:
    """SG-04: реквизиты сторон настоящие, а не правдоподобные.

    Номер, которого нет в материалах дела, в документ попасть не мог иначе как
    от модели. Номер, не проходящий контрольную сумму, суд отклоняет первым же
    действием, поэтому опечатка клиента — тоже основание не выпускать документ,
    а вернуться к клиенту за уточнением.
    """
    findings: list[LintFinding] = []
    context_numbers = set(style_guide.id_numbers_in(case_context)) if case_context else None

    for role, label in (("claimant", "истец"), ("defendant", "ответчик")):
        lines = [str(item) for item in (getattr(draft, role, None) or [])]
        if not lines:
            continue
        joined = " ".join(lines)

        for number in style_guide.id_numbers_in(joined):
            if context_numbers is not None and number not in context_numbers:
                findings.append(
                    _style_finding(
                        "SG-04",
                        role,
                        f"реквизит {number} ({label}) отсутствует в материалах дела",
                    )
                )
                continue
            if not style_guide.id_number_is_valid(number):
                findings.append(
                    _style_finding(
                        "SG-04",
                        role,
                        f"номер {number} ({label}) не проходит контрольную сумму ИИН/БИН",
                    )
                )

        if not style_guide.party_has_address(joined):
            findings.append(
                _style_finding("SG-04", role, f"в шапке нет адреса стороны ({label})")
            )
        if style_guide.party_is_legal_entity(joined) and not style_guide.party_has_bin(joined):
            findings.append(
                _style_finding("SG-04", role, f"юридическое лицо ({label}) указано без БИН")
            )
    return findings


def _check_structural_sections(draft: Any) -> list[LintFinding]:
    """SG-05: обязательные разделы — по структуре, а не по заголовку в тексте."""
    result = getattr(draft, "calculation_result", None)
    monetary = isinstance(result, dict) and _calculated(result, "claim_price") is not None
    missing = style_guide.missing_structural_sections(draft, monetary=monetary)
    return [
        _style_finding("SG-05", section, f"обязательный раздел «{section}» пуст")
        for section in missing
    ]


def lint_claim_document(draft: Any, *, case_context: str = "") -> LintResult:
    """Проверить собранный иск перед выдачей. PASS либо BLOCKED со списком нарушений.

    ``case_context`` — материалы дела. Без них проверка реквизитов сторон не
    может отличить номер, пришедший от клиента, от номера, который назвала
    модель, и ограничивается контрольной суммой.
    """
    findings: list[LintFinding] = []
    findings.extend(_check_service_markers(draft))
    findings.extend(_check_placeholders(draft))
    findings.extend(_check_calculation_readiness(draft))
    findings.extend(_check_articles(draft))
    findings.extend(_check_motions_against_attachments(draft))
    findings.extend(_check_amounts(draft))
    findings.extend(_check_style_guide(draft, case_context=case_context))

    status = LintStatus.BLOCKED if findings else LintStatus.PASS
    return LintResult(status=status, findings=findings)
