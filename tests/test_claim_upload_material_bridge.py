from __future__ import annotations

import asyncio
from types import SimpleNamespace

import korgan.claim_upload_material_bridge as bridge
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _empty_claim() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="500 000 ₸",
        facts=["По претензии заявлен возврат денег."],
        legal_basis=[],
        requests=[],
        attachments=["Досудебная претензия"],
        verification_notes=[],
        source_urls=[],
    )


def test_claim_aware_extractor_demands_marker_for_pretrial_documents() -> None:
    async def scenario() -> None:
        captured: dict = {}

        async def structured_response(**kwargs):
            captured.update(kwargs)
            return (
                {
                    "document_type": "Досудебная претензия",
                    "text_summary": "Требование вернуть оплату.",
                    "parties": ["Покупатель", "ТОО Ответчик"],
                    "identifiers": [],
                    "dates": ["01.08.2026"],
                    "amounts": ["500 000 тенге"],
                    "obligations": ["Вернуть оплату"],
                    "violations": ["Деньги не возвращены"],
                    "evidence": [],
                    "important_facts": [
                        "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: вернуть 500 000 тенге"
                    ],
                    "missing_or_unclear": [],
                },
                object(),
            )

        fake = SimpleNamespace(
            settings=SimpleNamespace(openai_vision_model="test", max_case_text_chars=10000),
            _structured_response=structured_response,
        )
        extracted = await bridge._claim_aware_extract_document(
            fake,
            b"Требую вернуть 500 000 тенге",
            "pretenziya.txt",
            "text/plain",
        )

        prompt = captured["content"][0]["content"][0]["text"]
        assert "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА:" in prompt
        assert extracted.important_facts == [
            "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: вернуть 500 000 тенге"
        ]
        assert "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА" in extracted.as_context()

    asyncio.run(scenario())


def test_empty_claim_prayer_is_recovered_from_uploaded_pretrial(monkeypatch) -> None:
    async def scenario() -> None:
        async def original_draft(_self, _context, _research, language="ru"):
            return _empty_claim()

        monkeypatch.setattr(bridge, "_ORIGINAL_DRAFT", original_draft)
        calls: list[dict] = []

        class FakeService:
            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                return {
                    "title": "Исковое заявление о взыскании денежных средств",
                    "court": "",
                    "claimant": ["Истец"],
                    "defendant": ["Ответчик"],
                    "price_of_claim": "500 000 ₸",
                    "facts": ["В претензии заявлен возврат 500 000 тенге."],
                    "legal_basis": [],
                    "requests": ["Взыскать с ответчика 500 000 тенге."],
                    "attachments": ["Досудебная претензия"],
                    "verification_notes": ["Правовое основание требует проверки."],
                }

        context = (
            "Файл: pretenziya.pdf\n"
            "Тип: Досудебная претензия\n"
            "Важные факты: ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: вернуть 500 000 тенге"
        )
        result = await bridge._draft_claim_with_uploaded_pretrial_recovery(
            FakeService(),
            context,
            _research(),
            language="ru",
        )

        assert result.requests == ["Взыскать с ответчика 500 000 тенге."]
        assert result.status is VerificationStatus.NEEDS_VERIFICATION
        assert len(calls) == 1
        assert "загруженная досудебная претензия" in calls[0]["issues"][0].lower()

    asyncio.run(scenario())
