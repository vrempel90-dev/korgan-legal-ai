from __future__ import annotations

"""Fast source-bound consultation from KORGAN's refreshed local Adilet corpus.

A consultation must not spend a minute opening dozens of URLs. The production
corpus is refreshed from Adilet separately; this adapter retrieves a small set
of relevant provisions locally, gives only those provisions to one structured
model call, then deterministically rejects any article the model was not shown.
The old web-bound consultation remains a fallback only when the local corpus is
unavailable or the fast model call itself fails.
"""

import logging
from typing import Any, Awaitable, Callable

from korgan.legal.pipeline import open_corpus
from korgan.professional_consultation import _NORMATIVE_ADVICE_RE
from korgan.provision_check import paraphrase_defects
from korgan.robust_production_legal import _is_adilet_source

LOGGER = logging.getLogger(__name__)

_FAST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "legal_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article_id": {"type": "string"},
                },
                "required": ["statement", "article_id"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "basis_article_id": {"type": "string"},
                },
                "required": ["text", "basis_article_id"],
                "additionalProperties": False,
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "basis_article_id": {"type": "string"},
                },
                "required": ["text", "basis_article_id"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "legal_points", "actions", "risks", "unknowns"],
    "additionalProperties": False,
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _candidate_block(provisions: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for provision in provisions:
        body = " ".join(str(provision.body or "").split())[:1800]
        parts.append(
            f"article_id={provision.article_id}\n"
            f"{provision.label()} — {provision.heading}\n"
            f"Редакция: {provision.edition_date}\n"
            f"Официальный источник: {provision.url}\n"
            f"Текст нормы: {body}"
        )
    return "\n\n---\n\n".join(parts)


def _render(
    payload: dict[str, Any],
    *,
    accepted: list[tuple[str, str, str]],
    accepted_ids: set[str],
    language: str,
) -> str:
    kk = language == "kk"
    summary = _clean(payload.get("summary"))

    def linked(items: list[dict[str, Any]]) -> list[str]:
        result: list[str] = []
        for item in items or []:
            text = _clean(item.get("text"))
            basis = _clean(item.get("basis_article_id"))
            if not text:
                continue
            if basis:
                if basis not in accepted_ids:
                    continue
            elif _NORMATIVE_ADVICE_RE.search(text):
                continue
            if text not in result:
                result.append(text)
        return result

    actions = linked(list(payload.get("actions") or []))
    risks = linked(list(payload.get("risks") or []))
    unknowns = [_clean(x) for x in list(payload.get("unknowns") or []) if _clean(x)]

    if kk:
        out = ["Қысқаша қорытынды", summary or "Сұрақ бойынша құқықтық жағдай талданды."]
        out.append("\nҚұқықтық негіз")
        if accepted:
            out.extend(f"{i}. {statement} ({label})" for i, (statement, label, _) in enumerate(accepted, 1))
        else:
            out.append("Берілген деректер бойынша нақты норманы сенімді растау мүмкін болмады.")
        if actions:
            out.append("\nНе істеу керек")
            out.extend(f"{i}. {text}" for i, text in enumerate(actions, 1))
        if risks:
            out.append("\nТәуекелдер")
            out.extend(f"• {text}" for text in risks)
        if unknowns:
            out.append("\nНақтылау қажет")
            out.extend(f"• {text}" for text in list(dict.fromkeys(unknowns))[:6])
        return "\n".join(out).strip()

    out = ["Краткий вывод", summary or "Правовая ситуация по вашему вопросу проанализирована."]
    out.append("\nПравовая оценка")
    if accepted:
        out.extend(f"{i}. {statement} ({label})" for i, (statement, label, _) in enumerate(accepted, 1))
    else:
        out.append("По имеющимся данным не удалось надёжно подтвердить конкретную норму для этого вывода.")
    if actions:
        out.append("\nЧто делать")
        out.extend(f"{i}. {text}" for i, text in enumerate(actions, 1))
    if risks:
        out.append("\nРиски")
        out.extend(f"• {text}" for text in risks)
    if unknowns:
        out.append("\nЧто требует уточнения")
        out.extend(f"• {text}" for text in list(dict.fromkeys(unknowns))[:6])
    return "\n".join(out).strip()


class FastLocalConsultationAdapter:
    def __init__(
        self,
        inner: Any,
        *,
        fallback: Callable[..., Awaitable[tuple[str, list[str]]]],
    ) -> None:
        self.inner = inner
        self.settings = inner.settings
        self.fallback = fallback

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        query = (str(question or "") + "\n" + str(case_context or "")[:8000]).strip()
        corpus = None
        try:
            corpus = open_corpus()
            if corpus is None:
                LOGGER.warning("FAST_LOCAL_CONSULT corpus unavailable; using web fallback")
                return await self.fallback(question, case_context=case_context, language=language)
            offered = corpus.search(query, limit=8)
        except Exception:
            LOGGER.exception("FAST_LOCAL_CONSULT corpus lookup failed; using web fallback")
            return await self.fallback(question, case_context=case_context, language=language)
        finally:
            if corpus is not None:
                corpus.close()

        provisions = {
            provision.article_id: provision
            for provision in offered
            if _is_adilet_source(str(provision.url or ""))
        }
        if not provisions:
            LOGGER.warning("FAST_LOCAL_CONSULT no Adilet candidates; using web fallback")
            return await self.fallback(question, case_context=case_context, language=language)

        prompt = (
            "Ответь клиенту как практикующий юрист Республики Казахстан. Используй ТОЛЬКО нормы, "
            "которые приведены ниже из локального корпуса KORGAN, обновляемого с Adilet.\n"
            "FACT LOCK: не придумывай даты, суммы, договоры, документы и действия сторон.\n"
            "Для каждого правового вывода укажи article_id ровно из предложенного списка. "
            "Если подходящей нормы нет — не выдумывай её, вынеси вопрос в unknowns.\n"
            "Дай короткий понятный ответ клиенту: вывод, применимое право, что делать и реальные риски.\n"
            f"Язык ответа: {'казахский' if language == 'kk' else 'русский'}.\n\n"
            f"ВОПРОС:\n{str(question or '')[:6000]}\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{str(case_context or '')[:10000] or 'нет'}\n\n"
            f"ПРОВЕРЕННЫЕ КАНДИДАТЫ ИЗ ADILET:\n{_candidate_block(tuple(provisions.values()))}"
        )

        try:
            payload, _ = await self.inner._structured_response(
                model=self.settings.openai_model,
                instructions=(
                    "Ты AI-юрист KORGAN. Отвечай кратко, профессионально и без веб-поиска. "
                    "Право разрешено брать только из предоставленных норм Adilet."
                ),
                content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                schema_name="korgan_fast_local_consultation",
                schema=_FAST_SCHEMA,
            )
        except Exception:
            LOGGER.exception("FAST_LOCAL_CONSULT model call failed; using web fallback")
            return await self.fallback(question, case_context=case_context, language=language)

        accepted: list[tuple[str, str, str]] = []
        accepted_ids: set[str] = set()
        sources: list[str] = []
        for raw in list(payload.get("legal_points") or []):
            statement = _clean(raw.get("statement"))
            article_id = _clean(raw.get("article_id"))
            provision = provisions.get(article_id)
            if not statement or provision is None:
                continue
            if paraphrase_defects(statement, str(provision.body or "")):
                continue
            accepted.append((statement, provision.label(), provision.url))
            accepted_ids.add(article_id)
            if provision.url not in sources:
                sources.append(provision.url)

        text = _render(
            payload,
            accepted=accepted,
            accepted_ids=accepted_ids,
            language=language,
        )
        LOGGER.info(
            "FAST_LOCAL_CONSULT candidates=%d accepted=%d sources=%d",
            len(provisions),
            len(accepted),
            len(sources),
        )
        return text, sources
