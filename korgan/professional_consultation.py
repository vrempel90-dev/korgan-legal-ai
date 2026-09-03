from __future__ import annotations

import logging
from datetime import date
from typing import Any

from korgan.provision_check import paraphrase_defects
from korgan.robust_production_legal import _is_adilet_source
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)

_CONSULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "qualification": {"type": "string"},
        "client_goal": {"type": "string"},
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "provision_text": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "provision_text", "source_url"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "basis_statement": {"type": "string"},
                },
                "required": ["action", "basis_statement"],
                "additionalProperties": False,
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string"},
                    "basis_statement": {"type": "string"},
                },
                "required": ["risk", "basis_statement"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "qualification", "client_goal", "verified_points", "actions", "risks", "unknowns"
    ],
    "additionalProperties": False,
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _linked_items(
    items: list[dict[str, Any]],
    *,
    text_key: str,
    accepted_statements: set[str],
) -> list[str]:
    """Keep neutral actions/risks or items explicitly tied to a verified point."""
    result: list[str] = []
    for item in items or []:
        text = _clean(item.get(text_key))
        basis = _clean(item.get("basis_statement"))
        if not text:
            continue
        # Empty basis is allowed only for non-normative practical advice such as
        # preserving evidence or obtaining a copy of an existing document. A
        # claimed legal basis must match an accepted source-bound statement.
        if basis and basis not in accepted_statements:
            continue
        if text not in result:
            result.append(text)
    return result


def _render_consultation(
    *,
    payload: dict[str, Any],
    verified: list[dict[str, str]],
    rejected: list[str],
    language: str,
) -> str:
    kk = language == "kk"
    qualification = _clean(payload.get("qualification"))
    goal = _clean(payload.get("client_goal"))
    accepted = {item["statement"] for item in verified}
    actions = _linked_items(
        list(payload.get("actions") or []),
        text_key="action",
        accepted_statements=accepted,
    )
    risks = _linked_items(
        list(payload.get("risks") or []),
        text_key="risk",
        accepted_statements=accepted,
    )
    unknowns = [_clean(x) for x in list(payload.get("unknowns") or []) if _clean(x)]
    unknowns.extend(x for x in rejected if x not in unknowns)

    if kk:
        parts = ["Қысқаша қорытынды"]
        if qualification:
            parts.append(qualification)
        if goal:
            parts.append(f"Клиенттің мақсаты: {goal}")
        parts.append("\nҚұқықтық негіз")
        if verified:
            parts.extend(
                f"{index}. {item['statement']} ({item['article']})"
                for index, item in enumerate(verified, 1)
            )
        else:
            parts.append(
                "Ресми дереккөзбен нақты құқықтық норманы растай алмадым; "
                "сондықтан бапты немесе құқықтық салдарды болжап жазбаймын."
            )
        if actions:
            parts.append("\nНе істеу керек")
            parts.extend(f"{index}. {item}" for index, item in enumerate(actions, 1))
        if risks:
            parts.append("\nТәуекелдер")
            parts.extend(f"• {item}" for item in risks)
        if unknowns:
            parts.append("\nНақты белгісіз")
            parts.extend(f"• {item}" for item in list(dict.fromkeys(unknowns))[:8])
        return "\n".join(parts).strip()

    parts = ["Краткий вывод"]
    if qualification:
        parts.append(qualification)
    if goal:
        parts.append(f"Цель клиента: {goal}")
    parts.append("\nПравовая оценка")
    if verified:
        parts.extend(
            f"{index}. {item['statement']} ({item['article']})"
            for index, item in enumerate(verified, 1)
        )
    else:
        parts.append(
            "Я не могу подтвердить конкретную правовую норму по официальному источнику, "
            "поэтому не буду придумывать статью или правовое последствие."
        )
    if actions:
        parts.append("\nЧто делать")
        parts.extend(f"{index}. {item}" for index, item in enumerate(actions, 1))
    if risks:
        parts.append("\nРиски")
        parts.extend(f"• {item}" for item in risks)
    if unknowns:
        parts.append("\nЧто нельзя установить из имеющихся материалов")
        parts.extend(f"• {item}" for item in list(dict.fromkeys(unknowns))[:8])
    return "\n".join(parts).strip()


class ProfessionalConsultationAdapter:
    """Source-bound consultation layer around the production legal service.

    The model may classify the issue and propose a strategy, but a legal rule is
    shown to the client only when the exact claimed source was actually opened
    during this response and the source is Adilet. Unknown facts stay unknown;
    the adapter never starts a questionnaire and never invents missing details.
    """

    def __init__(self, inner: Any):
        self.inner = inner
        self.settings = inner.settings

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]
        checked_on = date.today().isoformat()
        prompt = (
            f"Дата проверки права: {checked_on}.\n"
            f"Вопрос клиента:\n{question}\n\n"
            f"Материалы дела:\n{case_context[: self.settings.max_case_text_chars] if case_context else 'нет'}\n\n"
            "РАЗБЕРИ ВОПРОС КАК ПРАКТИКУЮЩИЙ ЮРИСТ РК.\n"
            "1. Сначала установи реальную цель клиента и юридическую природу вопроса. Не принимай бытовую формулировку клиента за готовую правовую квалификацию.\n"
            "2. FACT LOCK: используй только факты вопроса и материалов. Не добавляй даты, суммы, договоры, действия сторон или доказательства.\n"
            "3. Для каждого правового вывода найди действующую норму Республики Казахстан через web search. Нормативное право подтверждай по Adilet.\n"
            "4. Каждый verified_point: один конкретный вывод, точная статья/пункт, фрагмент нормы provision_text и URL страницы, реально открытой в этом ответе.\n"
            "5. Если норма не подтверждает statement прямо, не помещай вывод в verified_points. Не подбирай соседнюю статью по памяти.\n"
            "6. actions должны отвечать на вопрос клиента по существу. Если действие основано на правовой норме, basis_statement должен дословно совпадать с statement одного verified_point. Для чисто фактического действия basis_statement оставь пустым.\n"
            "7. Для юридического риска действует то же правило basis_statement. Непроверенное право не маскируй под риск.\n"
            "8. В unknowns перечисли только сведения, которых действительно нет в имеющемся контексте и которые materially влияют на вывод. Не превращай unknowns в анкету и не требуй заполнять форму.\n"
            "9. Не обещай исход дела. Не утверждай госпошлину, срок, подсудность, неустойку или обязательный досудебный порядок без прямой VERIFIED-нормы.\n"
            f"Рабочий язык: {'казахский' if language == 'kk' else 'русский'}."
        )
        payload, response = await self.inner._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты ведущий юрист KORGAN по праву Республики Казахстан. "
                "Отвечай по существу, fact-locked и source-bound. "
                "Никогда не заполняй пробелы догадками и не проводи анкетирование клиента."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_professional_consultation",
            schema=_CONSULT_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if self.inner._allowed_source(url)
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }

        verified: list[dict[str, str]] = []
        rejected: list[str] = []
        used_urls: list[str] = []
        for raw in list(payload.get("verified_points") or []):
            statement = _clean(raw.get("statement"))
            article = _clean(raw.get("article"))
            provision_text = _clean(raw.get("provision_text"))
            claimed_url = _clean(raw.get("source_url"))
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))

            if not statement or not article or not provision_text or not actual_url:
                if statement:
                    rejected.append(
                        f"Не подтверждено официальным источником: {statement}"
                        if language != "kk"
                        else f"Ресми дереккөзбен расталмады: {statement}"
                    )
                continue
            if not _is_adilet_source(actual_url):
                rejected.append(
                    f"Нормативный вывод не принят: источник не Adilet — {statement}"
                    if language != "kk"
                    else f"Нормативтік қорытынды қабылданбады: дереккөз Adilet емес — {statement}"
                )
                continue
            drift = paraphrase_defects(statement, provision_text)
            if drift:
                rejected.append(
                    f"Норма не подтверждает сформулированный вывод напрямую: {statement}"
                    if language != "kk"
                    else f"Норма тұжырымдалған қорытындыны тікелей растамайды: {statement}"
                )
                continue

            verified.append(
                {
                    "statement": statement,
                    "article": article,
                    "provision_text": provision_text,
                    "source_url": actual_url,
                }
            )
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        text = _render_consultation(
            payload=payload,
            verified=verified,
            rejected=rejected,
            language=language,
        )
        LOGGER.info(
            "PROFESSIONAL_CONSULT verified=%d rejected=%d sources=%d",
            len(verified),
            len(rejected),
            len(used_urls),
        )
        return text, used_urls
