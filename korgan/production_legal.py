from __future__ import annotations

import json

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA, _VALIDATION_SCHEMA
from korgan.verified_openai import VerifiedOpenAILegalService


class ProductionOpenAILegalService(VerifiedOpenAILegalService):
    """Source-bound service with stricter court-document drafting quality."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        verified_block = "\n".join(f"- {x}" for x in research.verified_claims) or "нет подтвержденных выводов"
        unverified_block = "\n".join(f"- {x}" for x in research.unverified_claims) or "нет"

        prompt = (
            "Сформируй СУДЕБНЫЙ ПРОЕКТ искового заявления для Республики Казахстан. "
            "Результат будет автоматически помещен в Word-файл, поэтому поля facts, legal_basis, requests и attachments "
            "должны содержать только текст, пригодный для самого судебного документа.\n\n"
            "ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА КАЧЕСТВА:\n"
            "1. Используй ВСЕ известные из материалов реквизиты сторон. Если в материалах есть ФИО, ИИН/БИН, адрес, телефон или e-mail, "
            "они должны попасть в claimant/defendant. НЕЛЬЗЯ заменять известное значение на '[указать]', '[при наличии]' или '[ТРЕБУЕТ УТОЧНЕНИЯ]'.\n"
            "2. Не придумывай неизвестное. Для реально отсутствующего обязательного реквизита используй только краткую пометку "
            "'[ТРЕБУЕТ УТОЧНЕНИЯ: ...]'.\n"
            "3. Факты изложи хронологично и юридически нейтрально: договор, передача денег/исполнение истцом, срок исполнения ответчиком, нарушение. "
            "Не повторяй один факт несколько раз.\n"
            "4. Правовое обоснование строится ТОЛЬКО на VERIFIED-выводах. Обязательно используй все прямо применимые VERIFIED-нормы материального права. "
            "Для спора из займа, если в VERIFIED есть статьи 715 и/или 722 ГК РК, они обязательно должны быть отражены в legal_basis.\n"
            "5. Процессуальные нормы включай только если они действительно нужны для иска и подтверждены: подсудность, содержание и приложения.\n"
            "6. Не пиши в судебной части слова NEEDS_VERIFICATION, 'можно адаптировать', 'что еще нужно сделать', 'если отправите данные', "
            "'на практике', советы пользователю, пояснения работы AI, список официальных URL или иные служебные комментарии.\n"
            "7. Все непроверенные вопросы вынеси ТОЛЬКО в verification_notes. Они будут показаны пользователю отдельно и не должны засорять тело иска.\n"
            "8. В attachments перечисляй конкретные документы, которые реально присутствуют в материалах. Если обязательного приложения нет, "
            "пиши '[ТРЕБУЕТ ДОБАВИТЬ: ...]'. Не пиши 'при наличии' для документа, который уже загружен/подтвержден материалами.\n"
            "9. Не включай доверенность представителя, расходы на представителя и другие условные пункты, если материалы не показывают, что они применимы.\n"
            "10. price_of_claim заполни известной суммой требования. Не подменяй известную цену иска заглушкой.\n"
            "11. Если точный суд не подтвержден, court может содержать только '[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда по месту жительства ответчика]'. "
            "Не выдумывай название суда.\n"
            "12. Не вставляй размер госпошлины, если он не VERIFIED. Отсутствие подтвержденного размера госпошлины фиксируй в verification_notes; "
            "в самом иске не создавай отдельный служебный блок про NEEDS_VERIFICATION.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified_block}\n\n"
            f"НЕ ПОДТВЕРЖДЕНО (только для verification_notes):\n{unverified_block}"
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный юрист KORGAN по праву Республики Казахстан. "
                "Пиши как готовый к вычитке судебный документ, без чатовых пояснений и без правовой фантазии. "
                f"Язык документа: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **payload)
        validation = await self.validate_claim(case_context, research, draft)
        problems = (
            validation["critical_errors"]
            + validation["unsupported_legal_claims"]
            + validation["missing_required_fields"]
        )

        # One repair pass only when the independent validator found an actual drafting defect.
        if problems:
            repair_prompt = (
                "Исправь проект иска по замечаниям валидатора. Сохрани fail-closed режим. "
                "Не добавляй новых фактов или норм. Верни полностью исправленную структуру иска.\n\n"
                f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
                f"VERIFIED:\n{verified_block}\n\n"
                f"ЗАМЕЧАНИЯ ВАЛИДАТОРА:\n{json.dumps(problems, ensure_ascii=False)}\n\n"
                f"ТЕКУЩИЙ ПРОЕКТ:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            repaired_payload, _ = await self._structured_response(
                model=self.settings.openai_model,
                instructions=(
                    "Ты редактор судебных документов KORGAN. Исправляй только выявленные дефекты; "
                    "не добавляй неподтвержденное право и не превращай иск в консультацию."
                ),
                content=[{"role": "user", "content": [{"type": "input_text", "text": repair_prompt}]}],
                schema_name="korgan_repaired_claim",
                schema=_CLAIM_SCHEMA,
            )
            draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **repaired_payload)
            validation = await self.validate_claim(case_context, research, draft)
            problems = (
                validation["critical_errors"]
                + validation["unsupported_legal_claims"]
                + validation["missing_required_fields"]
            )

        if problems or research.unverified_claims:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        if problems:
            draft.verification_notes.extend(x for x in problems if x not in draft.verification_notes)
        return draft

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        draft_text = json.dumps(
            {
                "title": draft.title,
                "court": draft.court,
                "claimant": draft.claimant,
                "defendant": draft.defendant,
                "price_of_claim": draft.price_of_claim,
                "facts": draft.facts,
                "legal_basis": draft.legal_basis,
                "requests": draft.requests,
                "attachments": draft.attachments,
            },
            ensure_ascii=False,
        )
        prompt = (
            "Проверь проект иска как строгий редактор перед выдачей клиенту. Найди:\n"
            "1) факты, которых нет в материалах;\n"
            "2) правовые утверждения, которых нет в VERIFIED;\n"
            "3) известные в материалах ФИО/ИИН/адрес/контакт/сумму, которые проект потерял или заменил заглушкой;\n"
            "4) загруженный/подтвержденный документ, который в attachments ошибочно назван 'при наличии';\n"
            "5) прямо применимую VERIFIED-норму материального права, которая необоснованно отсутствует в legal_basis;\n"
            "6) служебный или чатовый текст внутри судебных полей: NEEDS_VERIFICATION, 'что еще нужно сделать', 'можно адаптировать', "
            "'если отправите', советы пользователю, URL источников;\n"
            "7) условные требования/приложения, для которых нет фактического основания (представитель, его расходы и т.п.);\n"
            "8) иные обязательные поля, которые нельзя безопасно восстановить.\n"
            "Не требуй от проекта придумывать неизвестный точный суд или неподтвержденную госпошлину: для них допустима краткая пометка об уточнении.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:40000]}\n\n"
            f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"ПРОЕКТ:\n{draft_text}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_validation_model,
            instructions="Ты независимый валидатор судебных документов KORGAN. Будь строгим и fail-closed.",
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_validation",
            schema=_VALIDATION_SCHEMA,
        )
        return {
            "critical_errors": list(payload.get("critical_errors", [])),
            "unsupported_legal_claims": list(payload.get("unsupported_legal_claims", [])),
            "missing_required_fields": list(payload.get("missing_required_fields", [])),
        }
