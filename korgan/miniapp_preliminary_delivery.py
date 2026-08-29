"""Выдавать помеченный черновик вместо пустого отказа.

Что происходило
---------------
`miniapp_professional_release` при непрохождении финальной проверки СТИРАЛ
готовый документ и отдавал 422. В логах прода это выглядит так:

    FINALIZED_PROFESSIONAL_CLAIM score=8.4 ready=False
    MINIAPP_PROFESSIONAL_RELEASE_BLOCK case_id=KOR-2055C536BC16 score=8.4
      issues=['не определена госпошлина или подтвержденная льгота',
              'FILING_ACTION: указать банковские реквизиты истца-юридического лица']
    POST /miniapp/documents/generate 422 Unprocessable Content

Документ был написан, дважды доработан, получил 8.4 из 10 — и не дошёл до
оплатившего пользователя. Порог 8.5 при этом не абсолютная величина, а
внутренняя настройка, и часть «блокеров» — не дефекты, а подсказки юристу
(«указать банковские реквизиты перед подачей»).

Отдавать пустоту за деньги хуже, чем отдать честно помеченный черновик:
документ уже несёт штамп «KORGAN QA STATUS: PRELIMINARY DRAFT» и подвал
«перед подачей необходимо проверить реквизиты, доказательства, подсудность,
госпошлину и отмеченные системой вопросы». К нему добавляется понятный
человеку список того, что нужно дослать.

Переключатель
-------------
    KORGAN_PRELIMINARY_DELIVERY = on | off   (по умолчанию on)

`off` возвращает прежнее поведение — 422 и стёртый документ.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Awaitable, Callable

LOGGER = logging.getLogger(__name__)

FLAG_ENV = "KORGAN_PRELIMINARY_DELIVERY"
_OFF = {"0", "false", "no", "off"}
_INSTALLED = False

# Технические формулировки, которые нельзя показывать клиенту как есть.
_HUMAN_READABLE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"госпошлин", re.I), "уточнить размер государственной пошлины или основание льготы"),
    (re.compile(r"незаполненн\w*\s+обязательн", re.I), "заполнить оставшиеся поля документа — они отмечены в тексте"),
    (re.compile(r"source-bound|corpus", re.I), "сверить ссылки на статьи с действующей редакцией"),
    (re.compile(r"наименование суда|подсудност", re.I), "подтвердить точное наименование суда и территориальную подсудность"),
    (re.compile(r"неустойк|пен[яию]", re.I), "указать размер неустойки либо ставку, базу и период расчёта"),
    (re.compile(r"реквизит", re.I), "указать банковские реквизиты стороны"),
    (re.compile(r"доказательств", re.I), "приложить документы, подтверждающие обстоятельства"),
)


def preliminary_delivery_enabled() -> bool:
    return (os.getenv(FLAG_ENV) or "").strip().lower() not in _OFF


def humanize(issues: list[str]) -> list[str]:
    """Перевести внутренние формулировки гейтов в задачи для пользователя."""
    result: list[str] = []
    for issue in issues:
        text = " ".join(str(issue or "").split())
        if not text:
            continue
        # FILING_ACTION уже написан для человека — снимаем только префикс.
        if text.upper().startswith("FILING_ACTION:"):
            cleaned = text.split(":", 1)[1].strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
            continue
        for pattern, readable in _HUMAN_READABLE:
            if pattern.search(text):
                if readable not in result:
                    result.append(readable)
                break
    return result


def mark_preliminary(result: dict[str, Any], issues: list[str], case_id: str) -> dict[str, Any]:
    """Пометить уже сгенерированный документ как предварительный проект.

    Повторная генерация здесь была бы вредна вдвойне: удвоила бы стоимость и
    время, а документ должен выходить за одну-две минуты. Проверка качества
    уже отработала, её замечания просто переносятся в ответ.
    """
    todo = humanize(issues)
    result["filing_ready"] = False
    result["release_status"] = "preliminary"
    result["preliminary"] = True
    result["todo_before_filing"] = todo
    result["message"] = (
        "Документ готов как предварительный проект и помечен в самом файле. "
        "Перед подачей нужно закрыть отмеченные вопросы."
        + (" Что дослать: " + "; ".join(todo[:5]) if todo else "")
    )
    LOGGER.warning(
        "MINIAPP_PRELIMINARY_DELIVERY case_id=%s score=%r todo=%s",
        case_id,
        result.get("quality_score"),
        todo[:6],
    )
    return result
