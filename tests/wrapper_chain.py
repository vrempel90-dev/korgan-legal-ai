"""Обход цепочки production-обёрток вокруг обработчика.

KORGAN собирает боевой рантайм из ``install_*()``-обёрток: ``strict_bot``
последовательно заменяет модульные функции своими обёртками, и к моменту старта
один генератор документа может быть закрыт девятью слоями (гонки, владение
запросом, предоплата, подсказки клиенту, …).

Из-за этого ``inspect.getsource(module.handler)`` показывает только САМЫЙ
ВНЕШНИЙ слой. Тест, который ищет в этом тексте «request_is_current», зеленеет
ровно до тех пор, пока никто не добавит ещё одну обёртку, — и краснеет от
добавления слоя, хотя защита на месте. Именно так падали
test_new_document_request_scope и родственные проверки: свойство выполнялось,
проверка смотрела не туда.

Здесь исходники собираются по всей цепочке: сама функция, всё, что захвачено её
замыканием, и ``__wrapped__``. Проверка становится утверждением о боевой
конфигурации, а не о порядке установки патчей.
"""

from __future__ import annotations

import inspect
import types


def chain_sources(handler: object) -> list[str]:
    """Исходники обработчика и всех функций, до которых он дотягивается."""
    collected: list[str] = []
    _collect(handler, set(), collected)
    return collected


def chain_source_text(*handlers: object) -> str:
    """Единый текст всех слоёв нескольких обработчиков."""
    parts: list[str] = []
    for handler in handlers:
        parts.extend(chain_sources(handler))
    return "\n".join(parts)


def _collect(handler: object, seen: set[int], collected: list[str]) -> None:
    if not isinstance(handler, types.FunctionType) or id(handler) in seen:
        return
    seen.add(id(handler))

    try:
        collected.append(inspect.getsource(handler))
    except (OSError, TypeError):
        # Функция без доступного исходника (встроенная, собранная exec) —
        # пропускаем её саму, но продолжаем по замыканию.
        pass

    for cell in handler.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            # Ячейка ещё не заполнена — рекурсивная обёртка в процессе сборки.
            continue
        _collect(value, seen, collected)

    _collect(getattr(handler, "__wrapped__", None), seen, collected)
