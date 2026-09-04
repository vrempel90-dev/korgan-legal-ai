"""Постадийные тайминги production-генерации документа.

Бюджет на генерацию уже измеряется целиком (`document_latency_budget_runtime`),
но одно число TOTAL не отвечает на вопрос, ради которого его смотрят: какая
именно стадия съела минуту. Когда документ готовится 118 секунд, из строки
`DOCUMENT_GENERATION_LATENCY seconds=118` нельзя понять, ушло ли время в
source-bound research, в переписывание черновика или в рендер Word, — а значит
нельзя и решить, что ускорять. Здесь стадии измеряются по их фактическим
границам, а не по таймеру на экране клиента.

Замеры не влияют на результат: сбой самой инструментации не должен ронять
подготовку документа, поэтому запись тайминга не может выбросить исключение
в юридический конвейер.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

LOGGER = logging.getLogger(__name__)

#: Имена стадий фиксированы: по ним ищут в логах и строят отчёт о латентности.
FACT_EXTRACTION = "FACT_EXTRACTION"
LEGAL_RESEARCH = "LEGAL_RESEARCH"
CALCULATIONS = "CALCULATIONS"
DRAFTING = "DRAFTING"
LEGAL_QA = "LEGAL_QA"
DOCX_RENDER = "DOCX_RENDER"
DELIVERY = "DELIVERY"
TOTAL = "TOTAL"

#: По этим меткам латентность и ищут в логах после деплоя: первая — про
#: юридический конвейер, вторая — про весь путь задачи до документа у клиента.
PIPELINE_LABEL = "DOCUMENT_STAGE_LATENCY"
JOB_LABEL = "DOCUMENT_JOB_LATENCY"

STAGE_ORDER: tuple[str, ...] = (
    FACT_EXTRACTION,
    LEGAL_RESEARCH,
    CALCULATIONS,
    DRAFTING,
    LEGAL_QA,
    DOCX_RENDER,
    DELIVERY,
)


@dataclass
class StageTimings:
    """Накопитель длительностей стадий одной генерации."""

    document_type: str
    seconds: dict[str, float] = field(default_factory=dict)
    _started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Измерить одну стадию. Упавшая стадия тоже попадает в отчёт.

        Время неудачной стадии важнее времени удачной: именно на ней конвейер
        обычно и упирается в бюджет. Поэтому длительность записывается в
        `finally`, а исключение проходит дальше без изменений.
        """
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, time.perf_counter() - started)

    def record(self, name: str, seconds: float) -> None:
        self.seconds[name] = self.seconds.get(name, 0.0) + max(0.0, float(seconds))

    def total(self) -> float:
        return time.perf_counter() - self._started

    def as_log_line(self, *, status: str, label: str = PIPELINE_LABEL) -> str:
        measured = " ".join(
            f"{name}={self.seconds[name]:.2f}" for name in STAGE_ORDER if name in self.seconds
        )
        return (
            f"{label} document_type={self.document_type} status={status} "
            f"{measured} {TOTAL}={self.total():.2f}"
        ).replace("  ", " ")

    def log(self, *, status: str, label: str = PIPELINE_LABEL) -> None:
        """Одна строка на генерацию — её и читают при разборе латентности."""
        try:
            LOGGER.info("%s", self.as_log_line(status=status, label=label))
        except Exception:  # noqa: BLE001 - телеметрия не роняет выдачу документа
            LOGGER.warning("%s logging failed document_type=%s", label, self.document_type)
