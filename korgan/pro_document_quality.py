"""Единая политика качества генерации документов.

Проблема, которую решает модуль
--------------------------------
Параметры, определяющие качество документа, были разбросаны по семи модулям и
всюду заданы одинаково и жёстко:

    if model == "gpt-5.1" or model.startswith("gpt-5.1-"):
        kwargs["reasoning"] = {"effort": "none"}

    output_limits = {"korgan_court_ready_claim": 4300, ...}

Отключённое рассуждение и лимит в 4300 токенов уместны на служебных вызовах —
извлечении фактов, валидации, проверке применимости. На составлении искового
заявления они дают ровно тот результат, за который документ и ругают: модель
пишет первое, что пришло в голову, а затем упирается в лимит и ужимает каждый
раздел до двух-трёх строк.

Здесь введено одно различие: СОСТАВЛЕНИЕ документа против СЛУЖЕБНОГО вызова.

* Составление (`DRAFTING_SCHEMAS`) — разложить требование на элементы предмета
  доказывания, сопоставить их с материалами, подобрать нормы от требования,
  проверить арифметику. Это работа, ради которой reasoning существует.
  Получает effort и полный лимит вывода.
* Всё остальное — извлечение, исследование, валидация, критика — остаётся
  на прежних дешёвых настройках. Экономия сохраняется там, где она ничего
  не портит.

Оба параметра управляются переменными окружения, чтобы подбирать их без
редеплоя кода:

    KORGAN_DRAFT_REASONING_EFFORT   none|low|medium|high   (по умолчанию medium)
    KORGAN_DRAFT_OUTPUT_SCALE       множитель лимитов      (по умолчанию 1.0)
"""

from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger(__name__)

EFFORT_ENV = "KORGAN_DRAFT_REASONING_EFFORT"
SCALE_ENV = "KORGAN_DRAFT_OUTPUT_SCALE"

DEFAULT_DRAFT_EFFORT = "medium"
VALID_EFFORTS = frozenset({"none", "low", "medium", "high"})

# Схемы, за которыми стоит написание текста документа для клиента или суда.
# Сюда же входят схемы починки: правка иска — это то же составление, только с
# перечнем дефектов, и она точно так же требует рассуждения.
DRAFTING_SCHEMAS: frozenset[str] = frozenset(
    {
        # исковое заявление
        "korgan_court_ready_claim",
        "korgan_repaired_claim",
        "korgan_claim_draft",
        "korgan_claim_final_release_repair",
        "korgan_exemplar_architecture_repair",
        "korgan_fast_professional_claim",
        "korgan_fast_professional_repair",
        "korgan_professional_claim",
        "korgan_professional_claim_repair",
        "korgan_quality_repaired_claim",
        "korgan_senior_litigation_repair",
        "korgan_universal_quality_claim",
        # договор
        "korgan_contract_draft",
        "korgan_contract_repair",
        "korgan_universal_quality_contract",
        # отзыв на иск
        "korgan_response_draft",
        "korgan_universal_quality_response",
        "korgan_voice_response_to_claim",
        # досудебная претензия и ответ на неё
        "korgan_pretrial_demand",
        "korgan_pretrial_response",
        "korgan_10_of_10_pretrial",
        "korgan_10_of_10_pretrial_response",
        "korgan_voice_pretrial_response",
        "korgan_uploaded_pretrial_claim_recovery",
    }
)

# Лимиты вывода на составление. Иск с расчётом по периодам, разбором исковой
# давности и снятием возражений оппонента занимает 6–9 тысяч токенов; договор
# со всеми разделами — до 12 тысяч. Прежние 4300/5200 обрезали документ.
DRAFT_OUTPUT_LIMITS: dict[str, int] = {
    "korgan_court_ready_claim": 12000,
    "korgan_repaired_claim": 12000,
    "korgan_claim_draft": 12000,
    "korgan_claim_final_release_repair": 12000,
    "korgan_exemplar_architecture_repair": 12000,
    "korgan_fast_professional_claim": 12000,
    "korgan_fast_professional_repair": 12000,
    "korgan_professional_claim": 12000,
    "korgan_professional_claim_repair": 12000,
    "korgan_quality_repaired_claim": 12000,
    "korgan_senior_litigation_repair": 12000,
    "korgan_universal_quality_claim": 12000,
    "korgan_contract_draft": 14000,
    "korgan_contract_repair": 14000,
    "korgan_universal_quality_contract": 14000,
    "korgan_response_draft": 10000,
    "korgan_universal_quality_response": 10000,
    "korgan_voice_response_to_claim": 10000,
    "korgan_pretrial_demand": 7000,
    "korgan_pretrial_response": 7000,
    "korgan_10_of_10_pretrial": 7000,
    "korgan_10_of_10_pretrial_response": 7000,
    "korgan_voice_pretrial_response": 7000,
    "korgan_uploaded_pretrial_claim_recovery": 7000,
}


def is_drafting(schema_name: str) -> bool:
    """True, если за схемой стоит текст документа, а не служебная структура."""
    return schema_name in DRAFTING_SCHEMAS


def draft_effort() -> str:
    raw = (os.getenv(EFFORT_ENV) or "").strip().lower()
    if raw in VALID_EFFORTS:
        return raw
    if raw:
        LOGGER.warning("KORGAN %s=%r не распознан, используется %s", EFFORT_ENV, raw, DEFAULT_DRAFT_EFFORT)
    return DEFAULT_DRAFT_EFFORT


def _scale() -> float:
    raw = (os.getenv(SCALE_ENV) or "").strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("KORGAN %s=%r не число, масштаб лимитов не применён", SCALE_ENV, raw)
        return 1.0
    # Ниже половины лимит снова начинает резать документ, выше двух — только
    # жжёт бюджет: обе границы поставлены намеренно.
    return min(max(value, 0.5), 2.0)


def reasoning_for(schema_name: str, model: str) -> dict[str, str] | None:
    """Настройка reasoning для вызова, либо None — если параметр не нужен.

    Прежнее поведение (`effort: none`) сохраняется для всех служебных схем.
    Схемы составления получают рабочий effort.
    """
    if not (model == "gpt-5.1" or model.startswith("gpt-5.1-")):
        return None
    if is_drafting(schema_name):
        return {"effort": draft_effort()}
    return {"effort": "none"}


def output_limit_for(schema_name: str, current: int | None = None) -> int | None:
    """Лимит вывода: расширенный для составления, прежний для остального."""
    limit = DRAFT_OUTPUT_LIMITS.get(schema_name)
    if limit is None:
        return current
    scaled = int(limit * _scale())
    if current is not None and current > scaled:
        # Вызывающий уже поднял лимит выше (например, повторная попытка после
        # обрыва JSON) — не понижаем.
        return current
    return scaled


def apply(kwargs: dict, *, schema_name: str, model: str) -> dict:
    """Проставить reasoning и max_output_tokens в готовые kwargs вызова."""
    reasoning = reasoning_for(schema_name, model)
    if reasoning is not None:
        kwargs["reasoning"] = reasoning
    limit = output_limit_for(schema_name, kwargs.get("max_output_tokens"))
    if limit is not None:
        kwargs["max_output_tokens"] = limit
    return kwargs
