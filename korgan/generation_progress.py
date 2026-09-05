"""Что именно происходит с документом прямо сейчас.

Зачем
-----
Подготовка занимает около двух минут. Всё это время экран показывал одну
крутящуюся полосу и два состояния: «проверяю право» (20%) и «проверяю
документ» (80%). Между ними лежала минута с лишним, за которую на экране не
менялось ничего, — и человек, заплативший за документ, не мог отличить идущую
работу от зависшей.

Правило
-------
Отмечается только то, что действительно произошло. Стадия переключается на
фактической границе внутри конвейера, а не по таймеру на экране: проценты,
дорисованные клиентом, врут ровно в тот момент, когда работа встала.

Как устроено
------------
Конвейер не знает про задачи и базу, а задача не знает про внутренние границы
конвейера. Связывает их переменная контекста: задача кладёт в неё приёмник,
конвейер сообщает в него имя стадии. Без приёмника вызов не делает ничего —
поэтому тот же конвейер работает и в Telegram, где никакой строки задачи нет.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Callable, Iterator

LOGGER = logging.getLogger(__name__)

#: Имена стадий, которые видит клиент. Совпадают с границами внутри
#: `miniapp_api_v2._generate`; выдуманных промежуточных состояний здесь нет.
QUEUED = "queued"
STARTING = "starting"
LEGAL_RESEARCH = "legal_research"
DRAFTING = "drafting"
LEGAL_QA = "legal_qa"
DOCX_RENDER = "document_render"
DELIVERY = "delivery"
COMPLETED = "completed"

#: Доля пути, пройденная к моменту НАЧАЛА стадии. Числа — это порядок и
#: масштаб реальных стадий, а не предсказание оставшегося времени: обещать
#: секунды, которых никто не измерял, — то же самое враньё, только в цифрах.
STAGE_PROGRESS: dict[str, int] = {
    QUEUED: 0,
    STARTING: 5,
    LEGAL_RESEARCH: 15,
    DRAFTING: 45,
    LEGAL_QA: 70,
    DOCX_RENDER: 85,
    DELIVERY: 93,
    COMPLETED: 100,
}

#: Порядок шагов на экране подготовки.
STAGE_ORDER: tuple[str, ...] = (
    STARTING,
    LEGAL_RESEARCH,
    DRAFTING,
    LEGAL_QA,
    DOCX_RENDER,
    DELIVERY,
)

_SINK: contextvars.ContextVar[Callable[[str, int], None] | None] = contextvars.ContextVar(
    "korgan_generation_progress_sink",
    default=None,
)


def progress_for(stage: str) -> int:
    """Доля пути для стадии; неизвестное имя не двигает полосу вперёд."""
    return STAGE_PROGRESS.get(str(stage or ""), 0)


def stage_index(stage: str) -> int:
    """Порядковый номер шага на экране, -1 для служебных состояний."""
    try:
        return STAGE_ORDER.index(str(stage or ""))
    except ValueError:
        return -1


@contextmanager
def reporting_to(sink: Callable[[str, int], None] | None) -> Iterator[None]:
    """На время блока направить сообщения о стадиях в ``sink``."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def report(stage: str) -> None:
    """Сообщить, что конвейер перешёл к стадии ``stage``.

    Сбой самой отчётности не должен ронять подготовку документа: клиент
    предпочтёт документ с устаревшей строкой состояния отказу из-за неё.
    """
    sink = _SINK.get()
    if sink is None:
        return
    try:
        sink(str(stage), progress_for(stage))
    except Exception:  # noqa: BLE001 — телеметрия не роняет выдачу документа
        LOGGER.warning("KORGAN generation progress report failed stage=%s", stage)
