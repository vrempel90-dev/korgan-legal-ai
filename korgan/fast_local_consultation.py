from __future__ import annotations

"""Fast source-bound consultation from KORGAN's refreshed local Adilet corpus.

A consultation must not spend a minute opening dozens of URLs. The production
corpus is refreshed from Adilet separately; this adapter retrieves a small set
of relevant provisions locally, gives only those provisions to one structured
model call, then deterministically rejects any article the model was not shown.
The old web-bound consultation remains a fallback when the local corpus is
unavailable, stale, or the fast model call itself fails.
"""

import logging
import time
from typing import Any, Awaitable, Callable

from korgan import claim_corpus_health
from korgan.legal.pipeline import open_corpus
from korgan.legal_calc import today_kz
from korgan.professional_consultation import _NORMATIVE_ADVICE_RE
from korgan.provision_check import paraphrase_defects
from korgan.robust_production_legal import _is_adilet_source

LOGGER = logging.getLogger(__name__)

_FAST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # The model summary is intentionally not rendered directly. A
        # customer-facing legal conclusion is derived from accepted legal_points
        # below, so free prose can never bypass source binding.
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
                    "basis_statement": {"type": "string"},
                },
                "required": ["text", "basis_statement"],
                "additionalProperties": False,
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "basis_statement": {"type": "string"},
                },
                "required": ["text", "basis_statement"],
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


def _freshness_issue(corpus: Any, provisions: list[Any]) -> str:
    """Return the first snapshot problem for an act offered to this answer."""
    checked_on = today_kz()
    for act_id in sorted({str(item.act_id) for item in provisions if getattr(item, "act_id", None)}):
        issue = claim_corpus_health._snapshot_issue(corpus, act_id, today=checked_on)
        if issue:
            return issue
    return ""


def _render(
    payload: dict[str, Any],
    *,
    accepted: list[tuple[str, str, str]],
    language: str,
) -> str:
    kk = language == "kk"
    accepted_statements = {statement for statement, _, _ in accepted}

    # Never display the model's free-form summary as a legal conclusion. The
    # first accepted point has already passed offered-ID + provision-paraphrase
    # validation and is therefore the only safe source for the short conclusion.
    if accepted:
        summary = accepted[0][0]
    else:
        summary = (
            "Берілген деректер бойынша нақты құқықтық қорытындыны растайтын норма табылмады."
            if kk
            else "По имеющимся данным не удалось подтвердить норму для конкретного правового вывода."
        )

    def linked(items: list[dict[str, Any]]) -> list[str]:
        result: list[str] = []
        for item in items or []:
            text = _clean(item.get("text"))
            basis = _clean(item.get("basis_statement"))
            if not text:
                continue
            if basis:
                # A legal/procedural recommendation may rely only on the exact
                # statement that already survived provision validation. Merely
                # naming the same article is insufficient: one article can
                # contain several rules with different conditions.
                if basis not in accepted_statements:
                    continue
            elif _NORMATIVE_ADVICE_RE.search(text):
                # Empty basis is reserved for factual steps only, e.g. preserve
                # a receipt or obtain a copy of a document.
                continue
            if text not in result:
                result.append(text)
        return result

    actions = linked(list(payload.get("actions") or []))
    risks = linked(list(payload.get("risks") or []))
    unknowns = [_clean(x) for x in list(payload.get("unknowns") or []) if _clean(x)]

    if kk:
        out = ["Қысқаша қорытынды", summary]
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

    out = ["Краткий вывод", summary]
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
        total_started = time.perf_counter()
        query = (str(question or "") + "\n" + str(case_context or "")[:8000]).strip()
        corpus = None
        offered: list[Any] = []
        local_issue = ""
        local_started = time.perf_counter()
        try:
            corpus = open_corpus()
            if corpus is None:
                local_issue = "local corpus unavailable"
            else:
                offered = corpus.search(query, limit=8)
                if offered:
                    local_issue = _freshness_issue(corpus, offered)
                else:
                    local_issue = "local corpus returned no candidates"
        except Exception as exc:
            LOGGER.exception("FAST_LOCAL_CONSULT corpus lookup/health failed; using web fallback")
            local_issue = f"corpus health error: {type(exc).__name__}"
        finally:
            if corpus is not None:
                corpus.close()
        local_seconds = time.perf_counter() - local_started

        if local_issue:
            LOGGER.warning(
                "FAST_LOCAL_CONSULT path=web_fallback reason=%s local_search_seconds=%.3f",
                local_issue,
                local_seconds,
            )
            return await self.fallback(question, case_context=case_context, language=language)

        provisions = {
            provision.article_id: provision
            for provision in offered
            if _is_adilet_source(str(provision.url or ""))
        }
        if not provisions:
            LOGGER.warning(
                "FAST_LOCAL_CONSULT path=web_fallback reason=no_adilet_candidates local_search_seconds=%.3f",
                local_seconds,
            )
            return await self.fallback(question, case_context=case_context, language=language)

        prompt = (
            "Ответь клиенту как практикующий юрист Республики Казахстан. Используй ТОЛЬКО нормы, "
            "которые приведены ниже из локального корпуса KORGAN, обновляемого с Adilet.\n"
            "FACT LOCK: не придумывай даты, суммы, договоры, документы и действия сторон.\n"
            "Для каждого правового вывода укажи article_id ровно из предложенного списка. "
            "statement должен следовать непосредственно из текста этой нормы.\n"
            "Для каждого юридического action/risk basis_statement должен ДОСЛОВНО совпадать со statement "
            "одного legal_point. Оставляй basis_statement пустым только для чисто фактического действия, "
            "которое не утверждает право, обязанность, срок, подсудность, пошлину или иной правовой результат.\n"
            "Если подходящей нормы нет — не выдумывай её, вынеси вопрос в unknowns.\n"
            "Дай короткий понятный ответ клиенту: применимое право, что делать и реальные риски.\n"
            f"Язык ответа: {'казахский' if language == 'kk' else 'русский'}.\n\n"
            f"ВОПРОС:\n{str(question or '')[:6000]}\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{str(case_context or '')[:10000] or 'нет'}\n\n"
            f"ПРОВЕРЕННЫЕ КАНДИДАТЫ ИЗ ADILET:\n{_candidate_block(tuple(provisions.values()))}"
        )

        model_started = time.perf_counter()
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
            LOGGER.exception(
                "FAST_LOCAL_CONSULT path=web_fallback reason=model_error local_search_seconds=%.3f model_seconds=%.3f",
                local_seconds,
                time.perf_counter() - model_started,
            )
            return await self.fallback(question, case_context=case_context, language=language)
        model_seconds = time.perf_counter() - model_started

        accepted: list[tuple[str, str, str]] = []
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
            if provision.url not in sources:
                sources.append(provision.url)

        text = _render(
            payload,
            accepted=accepted,
            language=language,
        )
        LOGGER.info(
            "FAST_LOCAL_CONSULT path=local candidates=%d accepted=%d sources=%d local_search_seconds=%.3f model_seconds=%.3f total_seconds=%.3f",
            len(provisions),
            len(accepted),
            len(sources),
            local_seconds,
            model_seconds,
            time.perf_counter() - total_started,
        )
        return text, sources
