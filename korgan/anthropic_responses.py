"""Anthropic под интерфейсом Responses API, которым уже пользуется KORGAN.

Юридическое ядро обращается к модели из семи мест: базовый сервис и шесть
переопределений `_structured_response` в наследниках. Все они собирают один и
тот же словарь для `client.responses.create` и разбирают один и тот же ответ —
`output_text` для JSON и `output` для URL, реально открытых поиском. Менять
семь вызывающих мест ради второго провайдера значит семь раз переписать
проверенный код и получить семь способов разойтись.

Поэтому подменяется не вызывающий код, а сам клиент. Этот адаптер отвечает на
`responses.create(**kwargs)` теми же полями, что и OpenAI SDK, а внутри
переводит запрос в Messages API. Наследники продолжают работать без изменений,
а выбор провайдера остаётся одной строкой в конструкторе сервиса.

Чего адаптер намеренно НЕ делает:

* не смягчает привязку к источникам — `allowed_domains` переезжает в
  серверный web_search Anthropic один в один, и URL по-прежнему берутся только
  из объектов поиска и цитат, а не из текста, который напечатала модель;
* не выдаёт незавершённый ответ за завершённый — если модель не вызвала
  структурный инструмент, ответ помечается `incomplete`, и вызывающий код
  падает на разборе JSON так же, как он падает на обрезанном ответе OpenAI.

Отличие провайдеров, которое стоит знать: у OpenAI структура ответа держится
на `strict: true` в json_schema, у Anthropic — на обязательном вызове
инструмента со схемой. Когда в том же запросе работает web_search, вызов
инструмента нельзя сделать обязательным (иначе модель не сможет искать), и
схема удерживается инструкцией. Именно этот случай и закрывает проверка на
`incomplete` ниже.
"""

from __future__ import annotations

import json
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

# Веб-поиск на стороне Anthropic. Версия инструмента фиксируется явно: смена
# версии меняет форму ответа, а из неё извлекаются URL источников.
WEB_SEARCH_TOOL = "web_search_20250305"

# Four official-source searches are enough for the focused KORGAN pass
# (material rule, remedy, jurisdiction and duty). Anthropic's max_uses is a
# server-enforced cap, unlike prompt wording, and prevents one research step
# from consuming the entire two-minute document budget.
DEFAULT_WEB_SEARCH_MAX_USES = 4

# Anthropic требует max_tokens в каждом запросе. Значение по умолчанию должно
# вмещать полный проект иска, а не только компактный research JSON.
DEFAULT_MAX_TOKENS = 16000

# Перевод усилия из настроек KORGAN в `output_config.effort` Anthropic.
#
# Переводить обязательно, и не только ради качества. Умолчание Anthropic —
# `high`. korgan/pro_document_quality.py даёт `effort: none` всем служебным
# вызовам (извлечение, исследование, валидация, критика) именно потому, что там
# рассуждение ничего не улучшает, а стоит денег. Молча пропустить этот параметр
# значило бы поднять каждый служебный вызов с «none» до «high» и сжечь месячный
# бюджет на том, что раньше было самой дешёвой частью конвейера.
#
# «none» у Anthropic нет — самый экономный уровень называется `low`, он и
# подставляется. Обратное соответствие (low→none) не нужно: составление,
# наоборот, должно думать.
EFFORT_MAP = {"none": "low", "low": "low", "medium": "medium", "high": "high"}


class _Node:
    """Объект ответа, читаемый и как атрибуты, и как словарь.

    `_annotation_urls` в openai_legal.py ходит по атрибутам, а
    `_actual_response_urls` в verified_openai.py — сначала по `model_dump()`.
    Обе дороги должны приводить к одним и тем же URL, иначе один и тот же
    ответ даст разное число подтверждённых источников в разных модулях.
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data
        for key, value in data.items():
            setattr(self, key, _wrap(value))

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, Any]:
        return _dump(self._data, exclude_none=exclude_none)

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"_Node({self._data!r})"


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return _Node(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _dump(value: Any, *, exclude_none: bool) -> Any:
    if isinstance(value, dict):
        return {
            key: _dump(item, exclude_none=exclude_none)
            for key, item in value.items()
            if not (exclude_none and item is None)
        }
    if isinstance(value, list):
        return [_dump(item, exclude_none=exclude_none) for item in value]
    return value


def _data_url_parts(image_url: str) -> tuple[str, str] | None:
    """Разбирает `data:image/png;base64,...` на тип и данные."""
    if not image_url.startswith("data:") or ";base64," not in image_url:
        return None
    head, encoded = image_url.split(";base64,", 1)
    media_type = head[len("data:"):].strip() or "image/jpeg"
    return media_type, encoded


def _content_blocks(raw: Any) -> list[dict[str, Any]]:
    """Переводит блоки Responses API в блоки Messages API."""
    if isinstance(raw, str):
        return [{"type": "text", "text": raw}]

    blocks: list[dict[str, Any]] = []
    for part in raw or []:
        if isinstance(part, str):
            blocks.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            continue

        kind = part.get("type")
        if kind in {"input_text", "text", "output_text"}:
            blocks.append({"type": "text", "text": str(part.get("text", ""))})
        elif kind in {"input_image", "image"}:
            parts = _data_url_parts(str(part.get("image_url", "")))
            if parts is None:
                # Ссылку на удалённую картинку KORGAN не отправляет: материалы
                # приходят файлами и кодируются на месте. Молча проглотить блок
                # значит потерять доказательство, поэтому это ошибка.
                raise ValueError("Anthropic принимает изображение только как data:...;base64")
            media_type, encoded = parts
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": encoded},
            })
        elif kind in {"input_file", "document"}:
            encoded = part.get("file_data") or part.get("data") or ""
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": str(part.get("media_type") or "application/pdf"),
                    "data": str(encoded),
                },
            })
    return blocks


def _messages(raw_input: Any) -> list[dict[str, Any]]:
    if isinstance(raw_input, str):
        return [{"role": "user", "content": [{"type": "text", "text": raw_input}]}]

    messages: list[dict[str, Any]] = []
    for item in raw_input or []:
        if isinstance(item, str):
            messages.append({"role": "user", "content": [{"type": "text", "text": item}]})
            continue
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        # Роли, кроме user и assistant, у Anthropic живут в system.
        if role not in {"user", "assistant"}:
            role = "user"
        blocks = _content_blocks(item.get("content"))
        if blocks:
            messages.append({"role": role, "content": blocks})
    return messages


def _search_tools(tools: Any, ) -> list[dict[str, Any]]:
    """Переносит web_search вместе с ограничением по доменам.

    Список разрешённых доменов — это и есть обещание «только официальные
    источники». Если бы он потерялся при переводе, модель начала бы искать по
    всему интернету, а проверки ниже по конвейеру по-прежнему считали бы
    найденное официальным.
    """
    result: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict) or not str(tool.get("type", "")).startswith("web_search"):
            continue
        translated: dict[str, Any] = {
            "type": WEB_SEARCH_TOOL,
            "name": "web_search",
            "max_uses": DEFAULT_WEB_SEARCH_MAX_USES,
        }
        filters = tool.get("filters")
        if isinstance(filters, dict):
            allowed = [str(domain) for domain in filters.get("allowed_domains", []) or []]
            if allowed:
                translated["allowed_domains"] = allowed
            blocked = [str(domain) for domain in filters.get("blocked_domains", []) or []]
            if blocked:
                translated["blocked_domains"] = blocked
        result.append(translated)
    return result


def _effort(reasoning: Any) -> str | None:
    """Уровень усилия для Anthropic из поля `reasoning` вызова Responses API."""
    if not isinstance(reasoning, dict):
        return None
    requested = str(reasoning.get("effort") or "").strip().lower()
    return EFFORT_MAP.get(requested)


def _schema_tool(text: Any) -> tuple[str, dict[str, Any]] | None:
    """Достаёт json_schema из поля `text` Responses API."""
    if not isinstance(text, dict):
        return None
    fmt = text.get("format")
    if not isinstance(fmt, dict) or fmt.get("type") != "json_schema":
        return None
    name = str(fmt.get("name") or "structured_output")
    schema = fmt.get("schema")
    if not isinstance(schema, dict):
        return None
    return name, schema


def _translate_output(message: Any, schema_name: str) -> tuple[str, list[dict[str, Any]], str]:
    """Собирает из ответа Messages API текст JSON и объекты источников.

    Возвращает `(output_text, output, status)`. URL берутся из результатов
    серверного поиска и из цитат — то есть из того, что модель действительно
    открыла, а не из того, что она написала.
    """
    output: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    payload: str = ""

    for block in getattr(message, "content", []) or []:
        kind = getattr(block, "type", None)

        if kind == "tool_use" and getattr(block, "name", None) == schema_name:
            payload = json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False)

        elif kind == "web_search_tool_result":
            sources: list[dict[str, Any]] = []
            for found in getattr(block, "content", []) or []:
                url = getattr(found, "url", None)
                if isinstance(url, str) and url:
                    sources.append({"url": url, "title": getattr(found, "title", None)})
            output.append({"type": "web_search_call", "action": {"type": "search", "sources": sources}})

        elif kind == "text":
            for citation in getattr(block, "citations", []) or []:
                url = getattr(citation, "url", None)
                if isinstance(url, str) and url:
                    annotations.append({"type": "url_citation", "url": url})

    if annotations:
        output.append({"type": "message", "content": [{"type": "output_text", "annotations": annotations}]})

    stop_reason = str(getattr(message, "stop_reason", "") or "")
    # Обрыв по длине и несостоявшийся вызов инструмента — оба означают, что
    # структурного ответа нет. Назвать это завершённым ответом нельзя: дальше по
    # конвейеру пустой JSON превратился бы в документ без раздела.
    status = "completed" if payload and stop_reason != "max_tokens" else "incomplete"
    return payload, output, status


class AnthropicResponses:
    """Реализация `client.responses` поверх Anthropic Messages API."""

    def __init__(self, client: Any, *, model_map: dict[str, str], default_model: str, max_tokens: int):
        self._client = client
        self._model_map = model_map
        self._default_model = default_model
        self._max_tokens = max_tokens

    def _model(self, requested: str) -> str:
        return self._model_map.get(requested, self._default_model)

    async def create(self, **kwargs: Any) -> _Node:
        schema = _schema_tool(kwargs.get("text"))
        if schema is None:
            raise ValueError("KORGAN обращается к модели только за структурированным ответом")
        schema_name, json_schema = schema

        tools: list[dict[str, Any]] = [{
            "name": schema_name,
            "description": "Единственный способ вернуть результат. Поля обязательны.",
            "input_schema": json_schema,
        }]
        search = _search_tools(kwargs.get("tools"))
        tools.extend(search)

        system = str(kwargs.get("instructions") or "")
        if search:
            # Обязательный вызов инструмента отключил бы поиск, поэтому здесь
            # схему удерживает инструкция, а несоблюдение ловится как incomplete.
            tool_choice: dict[str, Any] = {"type": "auto"}
            system = (
                f"{system}\n\nСначала проверь источники через web_search, затем верни результат "
                f"единственным вызовом инструмента {schema_name}. Не отвечай обычным текстом."
            ).strip()
        else:
            tool_choice = {"type": "tool", "name": schema_name}

        request: dict[str, Any] = {
            "model": self._model(str(kwargs.get("model") or "")),
            "max_tokens": int(kwargs.get("max_output_tokens") or self._max_tokens),
            "messages": _messages(kwargs.get("input")),
            "tools": tools,
            "tool_choice": tool_choice,
        }
        if system:
            request["system"] = system
        effort = _effort(kwargs.get("reasoning"))
        if effort:
            request["output_config"] = {"effort": effort}

        message = await self._client.messages.create(**request)
        payload, output, status = _translate_output(message, schema_name)

        usage = getattr(message, "usage", None)
        node = _Node({
            "id": getattr(message, "id", ""),
            "model": getattr(message, "model", request["model"]),
            "status": status,
            "output_text": payload,
            "output": output,
            "incomplete_details": None if status == "completed" else {"reason": "max_output_tokens"},
            "usage": {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            },
        })
        if status != "completed":
            LOGGER.warning(
                "KORGAN Anthropic structured call incomplete: schema=%s stop_reason=%s",
                schema_name,
                getattr(message, "stop_reason", None),
            )
        return node


class AnthropicResponsesClient:
    """Клиент, подставляемый вместо AsyncOpenAI в юридическом сервисе."""

    def __init__(self, client: Any, *, model_map: dict[str, str], default_model: str, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.responses = AnthropicResponses(
            client,
            model_map=model_map,
            default_model=default_model,
            max_tokens=max_tokens,
        )
