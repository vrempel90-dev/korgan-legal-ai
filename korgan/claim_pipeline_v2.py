from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from korgan.legal.pipeline import CorpusResearch, research_from_corpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)

MODE_ENV = "KORGAN_CLAIM_PIPELINE_V2_MODE"
_ALLOWED_MODES = {"off", "observe", "active", "enforce"}
_MAX_PACKETS = 32
_MAX_NORM_BODY = 2200


_FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "стороны": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "роль": {"type": "string"},
                    "наименование_или_ФИО": {"type": "string"},
                    "статус": {"type": "string"},
                    "БИН_или_ИИН": {"type": "string"},
                    "адрес": {"type": "string"},
                    "телефон": {"type": "string"},
                    "email": {"type": "string"},
                    "банковские_реквизиты": {"type": "string"},
                },
                "required": [
                    "роль", "наименование_или_ФИО", "статус", "БИН_или_ИИН",
                    "адрес", "телефон", "email", "банковские_реквизиты",
                ],
                "additionalProperties": False,
            },
        },
        "основание": {
            "type": "object",
            "properties": {
                "тип_договора": {"type": "string"},
                "номер": {"type": "string"},
                "дата": {"type": "string"},
                "предмет": {"type": "string"},
                "срок_исполнения": {"type": "string"},
                "договорная_подсудность": {"type": "string"},
                "договорная_неустойка": {"type": "string"},
                "претензионный_порядок_в_договоре": {"type": "string"},
            },
            "required": [
                "тип_договора", "номер", "дата", "предмет", "срок_исполнения",
                "договорная_подсудность", "договорная_неустойка",
                "претензионный_порядок_в_договоре",
            ],
            "additionalProperties": False,
        },
        "хронология": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "дата": {"type": "string"},
                    "событие": {"type": "string"},
                    "документ": {"type": "string"},
                },
                "required": ["дата", "событие", "документ"],
                "additionalProperties": False,
            },
        },
        "обязательства": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "кто": {"type": "string"},
                    "что_должен": {"type": "string"},
                    "срок": {"type": "string"},
                    "исполнено": {"type": "string"},
                },
                "required": ["кто", "что_должен", "срок", "исполнено"],
                "additionalProperties": False,
            },
        },
        "нарушение": {
            "type": "object",
            "properties": {
                "в_чём": {"type": "string"},
                "дата_начала": {"type": "string"},
                "длится_ли": {"type": "boolean"},
            },
            "required": ["в_чём", "дата_начала", "длится_ли"],
            "additionalProperties": False,
        },
        "суммы": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "назначение": {"type": "string"},
                    "сумма": {"type": "number"},
                    "валюта": {"type": "string"},
                    "подтверждение": {"type": "string"},
                },
                "required": ["назначение", "сумма", "валюта", "подтверждение"],
                "additionalProperties": False,
            },
        },
        "досудебный_порядок": {
            "type": "object",
            "properties": {
                "претензия_направлена": {"type": "boolean"},
                "дата": {"type": "string"},
                "способ": {"type": "string"},
                "получена": {"type": "string"},
                "ответ": {"type": "string"},
            },
            "required": ["претензия_направлена", "дата", "способ", "получена", "ответ"],
            "additionalProperties": False,
        },
        "дефицит_данных": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "чего_нет": {"type": "string"},
                    "чем_подтверждается": {"type": "string"},
                    "критичность": {"type": "string"},
                },
                "required": ["чего_нет", "чем_подтверждается", "критичность"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "стороны", "основание", "хронология", "обязательства", "нарушение",
        "суммы", "досудебный_порядок", "дефицит_данных",
    ],
    "additionalProperties": False,
}

_QUALIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "вид_правоотношений": {"type": "string"},
        "требования": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "формулировка": {"type": "string"},
                    "тип": {"type": "string"},
                    "поисковые_запросы_НПА": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["формулировка", "тип", "поисковые_запросы_НПА"],
                "additionalProperties": False,
            },
        },
        "суд": {"type": "string"},
        "обоснование_выбора_суда": {"type": "string"},
        "подсудность": {
            "type": "object",
            "properties": {
                "суд_конкретно": {"type": "string"},
                "основание": {"type": "string"},
            },
            "required": ["суд_конкретно", "основание"],
            "additionalProperties": False,
        },
        "цена_иска": {
            "type": "object",
            "properties": {"сумма": {"type": "number"}, "расчёт": {"type": "string"}},
            "required": ["сумма", "расчёт"],
            "additionalProperties": False,
        },
        "госпошлина": {
            "type": "object",
            "properties": {
                "ставка": {"type": "string"},
                "сумма": {"type": "number"},
                "льгота_есть": {"type": "boolean"},
                "норма_нужна": {"type": "string"},
            },
            "required": ["ставка", "сумма", "льгота_есть", "норма_нужна"],
            "additionalProperties": False,
        },
        "досудебный_порядок": {
            "type": "object",
            "properties": {
                "обязателен": {"type": "boolean"},
                "источник": {"type": "string"},
                "соблюдён": {"type": "boolean"},
            },
            "required": ["обязателен", "источник", "соблюдён"],
            "additionalProperties": False,
        },
        "срок_давности": {
            "type": "object",
            "properties": {
                "дата_начала_течения": {"type": "string"},
                "истекает": {"type": "string"},
                "риск": {"type": "string"},
            },
            "required": ["дата_начала_течения", "истекает", "риск"],
            "additionalProperties": False,
        },
        "дефицит_данных": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "вид_правоотношений", "требования", "суд", "обоснование_выбора_суда",
        "подсудность", "цена_иска", "госпошлина", "досудебный_порядок",
        "срок_давности", "дефицит_данных",
    ],
    "additionalProperties": False,
}

_APPLICABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "нормы": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "акт": {"type": "string"},
                    "статья": {"type": "string"},
                    "редакция_из_корпуса": {"type": "string"},
                    "применима": {"type": "boolean"},
                    "роль": {"type": "string"},
                    "почему": {"type": "string"},
                    "уверенность": {"type": "string"},
                    "контраргумент_ответчика": {"type": "string"},
                },
                "required": [
                    "article_id", "акт", "статья", "редакция_из_корпуса", "применима",
                    "роль", "почему", "уверенность", "контраргумент_ответчика",
                ],
                "additionalProperties": False,
            },
        },
        "норма_не_найдена": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["нормы", "норма_не_найдена"],
    "additionalProperties": False,
}

_CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "несуществующие_или_устаревшие_ссылки": {"type": "array", "items": {"type": "string"}},
        "статьи_без_фактической_опоры": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"статья": {"type": "string"}, "чего_не_хватает": {"type": "string"}},
                "required": ["статья", "чего_не_хватает"],
                "additionalProperties": False,
            },
        },
        "факты_без_доказательств": {"type": "array", "items": {"type": "string"}},
        "нарушения_формы_и_содержания_иска": {"type": "array", "items": {"type": "string"}},
        "риск_возврата_иска": {
            "type": "object",
            "properties": {"есть": {"type": "boolean"}, "почему": {"type": "string"}},
            "required": ["есть", "почему"],
            "additionalProperties": False,
        },
        "арифметика": {"type": "array", "items": {"type": "string"}},
        "двойное_взыскание_неустойки": {
            "type": "object",
            "properties": {"есть": {"type": "boolean"}, "почему": {"type": "string"}},
            "required": ["есть", "почему"],
            "additionalProperties": False,
        },
        "уязвимости_для_возражений": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"довод_ответчика": {"type": "string"}, "как_закрыть": {"type": "string"}},
                "required": ["довод_ответчика", "как_закрыть"],
                "additionalProperties": False,
            },
        },
        "вердикт": {"type": "string"},
    },
    "required": [
        "несуществующие_или_устаревшие_ссылки", "статьи_без_фактической_опоры",
        "факты_без_доказательств", "нарушения_формы_и_содержания_иска",
        "риск_возврата_иска", "арифметика", "двойное_взыскание_неустойки",
        "уязвимости_для_возражений", "вердикт",
    ],
    "additionalProperties": False,
}


@dataclass(slots=True)
class ClaimPipelinePacket:
    facts: dict[str, Any]
    qualification: dict[str, Any]
    applicability: dict[str, Any]
    candidate_norms: list[dict[str, str]]


def claim_pipeline_v2_mode() -> str:
    mode = os.getenv(MODE_ENV, "off").strip().lower()
    return mode if mode in _ALLOWED_MODES else "off"


def _case_key(case_context: str, language: str) -> str:
    payload = (language + "\0" + case_context).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _draft_payload(draft: ClaimDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "court": draft.court,
        "claimant": draft.claimant,
        "defendant": draft.defendant,
        "price_of_claim": draft.price_of_claim,
        "state_duty": draft.state_duty,
        "facts": draft.facts,
        "legal_basis": draft.legal_basis,
        "late_interest": draft.late_interest,
        "requests": draft.requests,
        "attachments": draft.attachments,
    }


def _candidate_dicts(offered: CorpusResearch | None) -> list[dict[str, str]]:
    if offered is None:
        return []
    result: list[dict[str, str]] = []
    for provision in offered.provisions:
        result.append(
            {
                "article_id": provision.article_id,
                "акт": provision.act_title,
                "статья": provision.article_no,
                "пункт": provision.item_no or "",
                "заголовок": provision.heading,
                "текст": provision.body[:_MAX_NORM_BODY],
                "редакция_из_корпуса": provision.edition_date,
                "источник": provision.url,
            }
        )
    return result


def _search_query(qualification: dict[str, Any]) -> str:
    parts: list[str] = []
    relationship = str(qualification.get("вид_правоотношений", "")).strip()
    if relationship:
        parts.append(relationship)
    for requirement in qualification.get("требования", []) or []:
        if not isinstance(requirement, dict):
            continue
        wording = str(requirement.get("формулировка", "")).strip()
        if wording:
            parts.append(wording)
        for query in requirement.get("поисковые_запросы_НПА", []) or []:
            value = str(query).strip()
            if value:
                parts.append(value)
    return " ".join(dict.fromkeys(parts))[:4000]


def _applicable_candidates(packet: ClaimPipelinePacket) -> list[dict[str, str]]:
    accepted_ids = {
        str(item.get("article_id", ""))
        for item in packet.applicability.get("нормы", []) or []
        if isinstance(item, dict) and bool(item.get("применима"))
    }
    return [item for item in packet.candidate_norms if item.get("article_id") in accepted_ids]


def _augment_research_context(case_context: str, packet: ClaimPipelinePacket) -> str:
    applicable = _applicable_candidates(packet)
    return (
        case_context
        + "\n\n<структурированные_факты_pipeline_v2>\n"
        + _compact_json(packet.facts)
        + "\n</структурированные_факты_pipeline_v2>\n"
        + "<квалификация_pipeline_v2>\n"
        + _compact_json(packet.qualification)
        + "\n</квалификация_pipeline_v2>\n"
        + "<кандидаты_норм_pipeline_v2>\n"
        + _compact_json(applicable)
        + "\n</кандидаты_норм_pipeline_v2>\n"
        + "ВАЖНО: кандидаты норм выше получены из локального корпуса Adilet и НЕ являются VERIFIED сами по себе. "
        "Текущий production research обязан заново связать каждую используемую норму с реально открытым официальным источником, "
        "проверить её применимость к фактам и не переносить в иск непроверенное право. Корпус пока хранит текущую редакцию, "
        "поэтому историческую редакцию на дату спорного отношения нельзя считать подтверждённой только этим блоком."
    )


def _critic_issues(critic: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    issues.extend(str(x) for x in critic.get("несуществующие_или_устаревшие_ссылки", []) or [] if str(x).strip())
    for item in critic.get("статьи_без_фактической_опоры", []) or []:
        if isinstance(item, dict):
            article = str(item.get("статья", "")).strip()
            missing = str(item.get("чего_не_хватает", "")).strip()
            if article or missing:
                issues.append(f"{article}: {missing}".strip(": "))
    issues.extend(str(x) for x in critic.get("факты_без_доказательств", []) or [] if str(x).strip())
    issues.extend(str(x) for x in critic.get("нарушения_формы_и_содержания_иска", []) or [] if str(x).strip())
    return list(dict.fromkeys(issues))


class ClaimPipelineV2Adapter:
    """Guarded pre/post processor around the proven production legal service.

    off:     zero new model calls, exact legacy behaviour.
    observe: run stages 1/2/3 + critic, but keep legacy research input/output untouched.
    active:  feed structured facts/qualification/applicable corpus candidates into the
             existing source-bound research; final drafting still uses the proven core.
    enforce: active + critic can mark a draft NEEDS_VERIFICATION. No automatic rewrite.

    Any v2 exception fails open to the exact existing production path.
    """

    def __init__(self, inner: Any):
        self.inner = inner
        self.settings = inner.settings
        self._packets: OrderedDict[str, ClaimPipelinePacket] = OrderedDict()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def _structured(
        self,
        *,
        model: str,
        instructions: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload, _ = await self.inner._structured_response(
            model=model,
            instructions=instructions,
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name=schema_name,
            schema=schema,
        )
        return payload

    async def _extract_facts(self, case_context: str, language: str) -> dict[str, Any]:
        return await self._structured(
            model=self.settings.openai_validation_model,
            instructions=(
                "Ты модуль извлечения юридически значимых фактов KORGAN по Республике Казахстан. "
                "Не квалифицируй право, не называй статьи и не заполняй пробелы догадками."
            ),
            prompt=(
                "<документы>\n" + case_context[: self.settings.max_case_text_chars] + "\n</документы>\n\n"
                "Извлеки только факты из материалов. Ничего не квалифицируй и не подбирай статьи. "
                "Недостающий факт занеси в дефицит_данных и укажи, каким документом он обычно подтверждается. "
                "Неизвестные строковые поля оставляй пустыми. Для РК отсутствие ИИН/БИН, телефона и email стороны "
                "фиксируй как дефицит, если этих данных действительно нет в материалах. "
                f"Рабочий язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            schema_name="korgan_claim_v2_facts",
            schema=_FACTS_SCHEMA,
        )

    async def _qualify(self, facts: dict[str, Any], language: str) -> dict[str, Any]:
        return await self._structured(
            model=self.settings.openai_validation_model,
            instructions=(
                "Ты модуль квалификации KORGAN по Республике Казахстан. На этом этапе запрещено называть номера статей. "
                "Твоя задача — правовая природа спора и поисковые категории для базы НПА."
            ),
            prompt=(
                "<факты>\n" + _compact_json(facts) + "\n</факты>\n\n"
                "Определи вид правоотношений и требования. Статьи НЕ называй: сформируй поисковые запросы для базы НПА. "
                "Суд/подсудность, госпошлина, срок давности и досудебный порядок на этом этапе являются только рабочей гипотезой "
                "для последующей проверки нормами; если данных недостаточно, зафиксируй дефицит. Не придумывай конкретный суд. "
                "Не считай окончательную госпошлину вместо детерминированного расчётного модуля: если расчёт нельзя надёжно вывести "
                "только из фактов, оставь сумму 0 и поясни это. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            schema_name="korgan_claim_v2_qualification",
            schema=_QUALIFICATION_SCHEMA,
        )

    def _retrieve_candidates(self, qualification: dict[str, Any]) -> list[dict[str, str]]:
        query = _search_query(qualification)
        if not query:
            return []
        offered = research_from_corpus(query, limit=12)
        return _candidate_dicts(offered)

    async def _check_applicability(
        self,
        facts: dict[str, Any],
        candidates: list[dict[str, str]],
        language: str,
    ) -> dict[str, Any]:
        if not candidates:
            return {"нормы": [], "норма_не_найдена": []}
        return await self._structured(
            model=self.settings.openai_validation_model,
            instructions=(
                "Ты модуль проверки применимости норм KORGAN. Рассматривай исключительно нормы из блока <нормы>. "
                "Нормы по памяти запрещены. Наличие статьи в корпусе ещё не означает её применимость к делу."
            ),
            prompt=(
                "<факты>\n" + _compact_json(facts) + "\n</факты>\n"
                "<нормы>\n" + _compact_json(candidates) + "\n</нормы>\n\n"
                "По каждой норме проверь цепочку: факт из материалов → условие нормы → вывод о применимости. "
                "Если фактическое условие не подтверждено, норма неприменима. Не меняй article_id. "
                "Поле редакция_из_корпуса означает только снимок текущего локального корпуса; не утверждай историческую действительность "
                "нормы на дату спора без отдельной source-bound проверки. Если нужной нормы среди кандидатов нет, добавь поисковую фразу "
                "в норма_не_найдена вместо выдумывания статьи. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            schema_name="korgan_claim_v2_applicability",
            schema=_APPLICABILITY_SCHEMA,
        )

    async def _build_packet(self, case_context: str, language: str) -> ClaimPipelinePacket:
        facts = await self._extract_facts(case_context, language)
        qualification = await self._qualify(facts, language)
        candidates = self._retrieve_candidates(qualification)
        applicability = await self._check_applicability(facts, candidates, language)
        return ClaimPipelinePacket(
            facts=facts,
            qualification=qualification,
            applicability=applicability,
            candidate_norms=candidates,
        )

    def _remember(self, key: str, packet: ClaimPipelinePacket) -> None:
        self._packets[key] = packet
        self._packets.move_to_end(key)
        while len(self._packets) > _MAX_PACKETS:
            self._packets.popitem(last=False)

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        mode = claim_pipeline_v2_mode()
        if mode == "off":
            return await self.inner.research_case(case_context, language=language)

        try:
            packet = await self._build_packet(case_context, language)
            key = _case_key(case_context, language)
            self._remember(key, packet)
            LOGGER.info(
                "CLAIM_PIPELINE_V2_PREP mode=%s parties=%d requirements=%d candidates=%d applicable=%d gaps=%d",
                mode,
                len(packet.facts.get("стороны", []) or []),
                len(packet.qualification.get("требования", []) or []),
                len(packet.candidate_norms),
                len(_applicable_candidates(packet)),
                len(packet.facts.get("дефицит_данных", []) or []),
            )
            research_context = case_context if mode == "observe" else _augment_research_context(case_context, packet)
            return await self.inner.research_case(research_context, language=language)
        except Exception:
            LOGGER.exception("CLAIM_PIPELINE_V2_PREP_FAILED mode=%s; falling back to stable production research", mode)
            return await self.inner.research_case(case_context, language=language)

    async def _critic(
        self,
        packet: ClaimPipelinePacket,
        research: LegalResearch,
        draft: ClaimDraft,
        language: str,
    ) -> dict[str, Any]:
        return await self._structured(
            model=self.settings.openai_validation_model,
            instructions=(
                "Ты независимый процессуальный оппонент KORGAN. Не переписывай иск и не добавляй право по памяти. "
                "Проверяй только против структурированных фактов и VERIFIED-норм production research."
            ),
            prompt=(
                "<иск>\n" + _compact_json(_draft_payload(draft)) + "\n</иск>\n"
                "<факты>\n" + _compact_json(packet.facts) + "\n</факты>\n"
                "<verified_нормы>\n" + _compact_json(research.verified_claims) + "\n</verified_нормы>\n\n"
                "Найди слабые места: ссылки без VERIFIED-опоры, статьи без фактической опоры, факты без доказательств, "
                "дефекты формы/содержания, риск возврата, арифметические противоречия и риск двойного взыскания неустойки. "
                "Не считай отсутствие необязательного документа ошибкой. Вердикт: подавать | доработать | не подавать. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            schema_name="korgan_claim_v2_critic",
            schema=_CRITIC_SCHEMA,
        )

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await self.inner.draft_claim(case_context, research, language=language)
        mode = claim_pipeline_v2_mode()
        if mode == "off":
            return draft

        packet = self._packets.pop(_case_key(case_context, language), None)
        if packet is None:
            LOGGER.info("CLAIM_PIPELINE_V2_CRITIC_SKIPPED no_packet mode=%s", mode)
            return draft

        try:
            critic = await self._critic(packet, research, draft, language)
            issues = _critic_issues(critic)
            verdict = str(critic.get("вердикт", "")).strip().lower()
            LOGGER.info(
                "CLAIM_PIPELINE_V2_CRITIC mode=%s verdict=%s issues=%d return_risk=%s double_penalty=%s",
                mode,
                verdict,
                len(issues),
                bool((critic.get("риск_возврата_иска") or {}).get("есть")),
                bool((critic.get("двойное_взыскание_неустойки") or {}).get("есть")),
            )
            if mode != "enforce":
                return draft

            hard = list(issues)
            return_risk = critic.get("риск_возврата_иска") or {}
            if bool(return_risk.get("есть")):
                reason = str(return_risk.get("почему", "")).strip()
                hard.append("Риск возврата иска" + (f": {reason}" if reason else ""))
            double = critic.get("двойное_взыскание_неустойки") or {}
            if bool(double.get("есть")):
                reason = str(double.get("почему", "")).strip()
                hard.append("Проверить недопустимое двойное взыскание неустойки" + (f": {reason}" if reason else ""))

            if verdict in {"доработать", "не подавать"} or hard:
                draft.status = VerificationStatus.NEEDS_VERIFICATION
                for issue in list(dict.fromkeys(hard))[:8]:
                    note = "Дополнительная процессуальная проверка: " + issue
                    if note not in draft.verification_notes:
                        draft.verification_notes.append(note)
            return draft
        except Exception:
            LOGGER.exception("CLAIM_PIPELINE_V2_CRITIC_FAILED mode=%s; keeping stable production draft", mode)
            return draft
