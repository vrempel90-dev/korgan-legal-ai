"""Детерминированная квалификация истца как потребителя.

Статус потребителя в Казахстане — это факт о цели приобретения: физическое
лицо, приобретающее товар (работу, услугу) для личных, семейных, домашних нужд,
не связанных с предпринимательской деятельностью. Подтверждение статьи Закона
«О защите прав потребителей» подтверждает текст нормы, но ничего не говорит о
том, подпадает ли под неё истец.

Раньше пайплайн этих двух вещей не различал: достаточно было, чтобы модель
написала слово «потребитель», а исследование вернуло VERIFIED-норму ЗПП. Так
физическое лицо, заказавшее корпоративный сайт, получало отсрочку госпошлины и
потребительскую подсудность — квалификацию, которую суд не примет.

Модуль отвечает ровно на один вопрос и отвечает fail-closed: цель приобретения
установлена как личная, установлена как предпринимательская, или не установлена
вовсе. Из «не установлена» никакие потребительские последствия не следуют.
"""

from __future__ import annotations

import re
from enum import StrEnum

from korgan.legal_calc import claimant_is_individual
from korgan.legal_types import ClaimDraft


class ConsumerStatus(StrEnum):
    ESTABLISHED = "established"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


# Цель прямо названа личной. Формулировки узкие: «для себя» или «лично» без
# указания на нужду сюда не входят — это разговорная речь, а не цель сделки.
_PERSONAL_PURPOSE_RE = re.compile(
    r"(?:для\s+(?:личн\w*|семейн\w*|домашн\w*|бытов\w*)(?:[\s,и]+(?:личн\w*|семейн\w*|домашн\w*|бытов\w*))*"
    r"\s+(?:нужд\w*|цел\w*|потребност\w*|использован\w*|пользован\w*|потреблен\w*)|"
    r"в\s+личн\w*\s+цел\w*|"
    r"для\s+личн\w*\s+(?:пользован\w*|использован\w*|потреблен\w*)|"
    r"не\s+связан\w*\s+с\s+(?:осуществлен\w*\s+)?предпринимательск\w*\s+деятельност\w*|"
    r"жеке\s+(?:қажеттілік\w*|тұтыну\w*|мұқтаж\w*)|"
    r"кәсіпкерлік\s+қызмет\w*\s*(?:пен|мен)\s+байланысты\s+емес)",
    re.IGNORECASE,
)

# Цель прямо названа предпринимательской либо объект сделки предназначен для
# бизнеса. Корпоративный сайт, вывеска компании, оборудование для торговой точки
# приобретаются не для домашних нужд.
_BUSINESS_PURPOSE_RE = re.compile(
    r"(?:в\s+(?:предпринимательск\w*|коммерческ\w*|business)\s+цел\w*|"
    r"для\s+(?:предпринимательск\w*|коммерческ\w*|производственн\w*)\s+(?:деятельност\w*|цел\w*|использован\w*)|"
    r"корпоративн\w*\s+(?:сайт\w*|портал\w*|систем\w*|почт\w*)|"
    r"для\s+(?:нужд\s+)?(?:компани\w*|фирм\w*|бизнес\w*|организаци\w*|предприяти\w*)|"
    r"для\s+(?:ТОО|АО|ИП)\b|"
    r"кәсіпкерлік\s+мақсат\w*)",
    re.IGNORECASE,
)

# Истец действует как предприниматель: тогда приобретение относится к его
# деятельности, а не к личным нуждам, даже если он физическое лицо.
_ENTREPRENEUR_CLAIMANT_RE = re.compile(
    r"(?:\bИП\b|индивидуальн\w*\s+предпринимател\w*|\bжеке\s+кәсіпкер\w*)",
    re.IGNORECASE,
)

_CLAIMANT_SEGMENT_RE = re.compile(
    r"(?is)(?:истец|талап\s+қоюшы)\s*:\s*(.*?)(?=(?:\n|;)\s*(?:ответчик|жауапкер)\s*:|\Z)",
)

# Утверждение о применении потребительского закона — не любое упоминание слова
# «потребитель». Название приложенной претензии иском о защите прав потребителя
# документ не делает.
_CONSUMER_ASSERTION_RE = re.compile(
    r"(?:Z100000274_|"
    r"защит\w*\s+прав\w*\s+потребител\w*|"
    r"(?:явля\w*|признан\w*|выступа\w*)\w*\s+потребител\w*|"
    r"истец\s*(?:—|–|-)\s*потребител\w*|"
    r"истец\s+как\s+потребител\w*|"
    r"прав\w*\s+потребител\w*\s+(?:нарушен\w*|подлежат)|"
    r"тұтынушылардың\s+құқықтарын\s+қорға)",
    re.IGNORECASE,
)


def _claimant_segment(case_context: str, draft: ClaimDraft) -> str:
    parts = [" ".join(str(item) for item in draft.claimant or [])]
    match = _CLAIMANT_SEGMENT_RE.search(case_context or "")
    if match:
        parts.append(match.group(1))
    return "\n".join(parts)


def _claimant_is_individual(case_context: str, draft: ClaimDraft) -> bool | None:
    """Физическое ли лицо истец — по контексту, а при молчании контекста по иску.

    Контекст не всегда оформлен как «Истец: …»: реквизиты приходят из загруженных
    материалов в произвольном виде. Тогда сторону определяет сам иск, где истец
    уже выделен отдельным полем.
    """
    result = claimant_is_individual(case_context)
    if result is not None:
        return result
    party = " ".join(str(item) for item in draft.claimant or [])
    if not party.strip():
        return None
    return claimant_is_individual(f"Истец: {party}")


def _factual_record(case_context: str, draft: ClaimDraft) -> str:
    """Материалы дела: контекст и факты — но не правовые выводы модели.

    Цель приобретения берётся только оттуда, где излагаются обстоятельства.
    Раздел правового обоснования вывод и содержит, поэтому доказательством
    собственной предпосылки быть не может.
    """
    return "\n".join([case_context or "", *(str(item) for item in draft.facts or [])])


def consumer_status(case_context: str, draft: ClaimDraft) -> ConsumerStatus:
    """Установлен ли статус потребителя по материалам дела."""
    individual = _claimant_is_individual(case_context, draft)
    if individual is False:
        return ConsumerStatus.EXCLUDED

    segment = _claimant_segment(case_context, draft)
    if _ENTREPRENEUR_CLAIMANT_RE.search(segment):
        return ConsumerStatus.EXCLUDED

    record = _factual_record(case_context, draft)
    if _BUSINESS_PURPOSE_RE.search(record):
        return ConsumerStatus.EXCLUDED
    if not _PERSONAL_PURPOSE_RE.search(record):
        return ConsumerStatus.UNKNOWN
    if individual is not True:
        # Цель личная, но сам истец физическим лицом не подтверждён: сначала
        # сторона, потом её защита.
        return ConsumerStatus.UNKNOWN
    return ConsumerStatus.ESTABLISHED


def asserts_consumer_law(draft: ClaimDraft) -> bool:
    """Опирается ли сам иск на потребительскую квалификацию."""
    text = "\n".join(
        [
            str(draft.title or ""),
            *(str(item) for item in draft.legal_basis or []),
            *(str(item) for item in draft.requests or []),
            *(str(item) for item in draft.facts or []),
        ]
    )
    return bool(_CONSUMER_ASSERTION_RE.search(text))
