from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.claim_filing_accuracy import _economic_registry_court
from korgan.legal_types import ClaimDraft, ContractDraft, LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft
from korgan.pretrial_response import PretrialResponseDraft
from korgan.response_types import ResponseToClaimDraft
from korgan.universal_word_quality_guard import (
    TARGET_READY_SCORE,
    finalize_claim_for_release,
    repair_pretrial_response_to_target,
    repair_pretrial_to_target,
    sanitize_draft_instructions,
)


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _claim_for_penalty() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании задолженности и договорной неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=[
            "ТОО «KAZTECH SOLUTIONS», БИН 230740012345, г. Астана",
            "Телефон, электронный адрес: при наличии указать",
        ],
        defendant=["ТОО «ASTANA INDUSTRY GROUP», БИН 210940067891, г. Астана"],
        price_of_claim="12 000 000 тенге",
        facts=[
            "Основной долг составляет 12 000 000 тенге.",
            "Договорная неустойка начислена за 83 дня и составила 996 000 тенге.",
            "Лимит неустойки по договору — не более 10%, то есть 1 200 000 тенге.",
        ],
        legal_basis=["Обязательство должно исполняться надлежащим образом."],
        requests=["Взыскать с ответчика основной долг в размере 12 000 000 тенге."],
        attachments=["Договор", "Товарная накладная", "Досудебная претензия"],
        verification_notes=["KORGAN QUALITY 8.0/10: потеряна неустойка"],
        source_urls=[],
    )


def test_quality_target_is_ten_without_removing_preliminary_fallback() -> None:
    assert TARGET_READY_SCORE == 10.0


def test_astana_economic_court_is_in_verified_registry() -> None:
    assert _economic_registry_court("Астана") == "Специализированный межрайонный экономический суд города Астаны"


def test_claim_restores_secondary_penalty_recalculates_price_and_state_duty() -> None:
    draft = _claim_for_penalty()
    context = (
        "Файл: pretenziya.pdf\n"
        "Тип: Досудебная претензия\n"
        "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: взыскать договорную неустойку в размере 996 000 тенге.\n"
        "Истец является ТОО; Ответчик является ТОО."
    )

    finalize_claim_for_release(context, draft)

    prayer = "\n".join(draft.requests).lower()
    assert "996 000 тенге" in prayer
    assert "неустой" in prayer
    assert draft.price_of_claim == "12 996 000 тенге"
    assert draft.state_duty.startswith("389 880 тенге")
    assert "[ТРЕБУЕТ РАСЧЁТА" not in draft.state_duty
    assert all("при наличии указать" not in item.lower() for item in draft.claimant)
    assert all(not note.startswith("KORGAN QUALITY") for note in draft.verification_notes)


def test_claim_does_not_invent_penalty_when_source_only_describes_contract_clause() -> None:
    draft = _claim_for_penalty()
    context = (
        "Договор предусматривает неустойку 0,1% за каждый день просрочки, но не более 10%.\n"
        "Клиент просит взыскать только основной долг 12 000 000 тенге."
    )

    finalize_claim_for_release(context, draft)

    prayer = "\n".join(draft.requests).lower()
    assert "996 000" not in prayer
    assert "неустой" not in prayer
    assert draft.price_of_claim == "12 000 000 тенге"


def test_restored_penalty_respects_kazakh_document_language() -> None:
    draft = _claim_for_penalty()
    draft.requests = ["Жауапкерден 12 000 000 теңге негізгі борышты өндіріп алу."]
    context = "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: 996 000 теңге тұрақсыздық айыбын өндіріп алу."

    finalize_claim_for_release(context, draft, language="kk")

    prayer = "\n".join(draft.requests)
    assert "996 000 теңге" in prayer
    assert "тұрақсыздық айыбын" in prayer
    assert "Взыскать" not in prayer


def test_instruction_cleanup_applies_to_all_five_document_shapes() -> None:
    claim = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск",
        court="",
        claimant=["Телефон, электронный адрес: при наличии указать"],
        defendant=["Ответчик"],
        price_of_claim="",
        facts=[],
        legal_basis=[],
        requests=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )
    contract = ContractDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        contract_type="Договор услуг",
        title="Договор",
        place_and_date="Астана",
        party_a=["Заказчик"],
        party_b=["Исполнитель"],
        preamble=[],
        sections=[],
        requisites_a=["Банковские реквизиты, телефон, электронный адрес: если известны — указать"],
        requisites_b=["БИН 123456789012"],
        verification_notes=[],
        source_urls=[],
    )
    response = ResponseToClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        claimant=["Истец"],
        defendant=["Телефон, электронный адрес: при наличии указать"],
    )
    pretrial = PretrialDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Досудебная претензия",
        sender=["Телефон, электронный адрес: при наличии указать"],
        recipient=["Адресат"],
        facts=[],
        legal_basis=[],
        demands=[],
        deadline="",
        consequences=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )
    pretrial_response = PretrialResponseDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Ответ на претензию",
        sender=["Отправитель"],
        recipient=["Банковские реквизиты, телефон, электронный адрес: если известны — указать"],
        reference="",
        claim_summary=[],
        position=[],
        objections=[],
        legal_basis=[],
        response_terms=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )

    for draft in (claim, contract, response, pretrial, pretrial_response):
        sanitize_draft_instructions(draft)

    assert claim.claimant == []
    assert contract.requisites_a == []
    assert response.defendant == []
    assert pretrial.sender == []
    assert pretrial_response.recipient == []


def test_pretrial_gets_one_bounded_repair_for_any_release_issue() -> None:
    async def scenario() -> None:
        defective = PretrialDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            title="Досудебная претензия",
            sender=["ТОО А"],
            recipient=["ТОО Б"],
            facts=["Товар поставлен, оплата не поступила."],
            legal_basis=[],
            demands=[],
            deadline="",
            consequences=[],
            attachments=["Договор"],
            verification_notes=[],
            source_urls=[],
        )

        async def original(_self, _context, _research, language="ru"):
            return defective

        calls: list[dict] = []

        class FakeService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                return {
                    "title": "Досудебная претензия",
                    "sender": ["ТОО А"],
                    "recipient": ["ТОО Б"],
                    "facts": ["Товар поставлен, оплата не поступила."],
                    "legal_basis": [],
                    "demands": ["Требуем оплатить задолженность 500 000 тенге."],
                    "deadline": "",
                    "consequences": ["При неисполнении возможно обращение в суд."],
                    "attachments": ["Договор"],
                    "verification_notes": [],
                }

        result = await repair_pretrial_to_target(
            FakeService(),
            original,
            "ТОО Б не оплатило 500 000 тенге",
            _research(),
            "ru",
        )
        assert len(calls) == 1
        assert result.demands == ["Требуем оплатить задолженность 500 000 тенге."]

    asyncio.run(scenario())


def test_pretrial_repair_failure_returns_original_preliminary_instead_of_killing_word() -> None:
    async def scenario() -> None:
        defective = PretrialDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            title="Досудебная претензия",
            sender=["ТОО А"],
            recipient=["ТОО Б"],
            facts=["Товар поставлен, оплата не поступила."],
            legal_basis=[],
            demands=[],
            deadline="",
            consequences=[],
            attachments=["Договор"],
            verification_notes=[],
            source_urls=[],
        )

        async def original(_self, _context, _research, language="ru"):
            return defective

        class FailingService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **_kwargs):
                raise TimeoutError("repair timeout")

        result = await repair_pretrial_to_target(
            FailingService(),
            original,
            "ТОО Б не оплатило 500 000 тенге",
            _research(),
            "ru",
        )
        assert result is defective
        assert result.status is VerificationStatus.NEEDS_VERIFICATION
        assert result.sender == ["ТОО А"]
        assert result.recipient == ["ТОО Б"]
        assert result.verification_notes

    asyncio.run(scenario())


def test_pretrial_response_gets_one_bounded_repair_for_any_release_issue() -> None:
    async def scenario() -> None:
        defective = PretrialResponseDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            title="Ответ на претензию",
            sender=["ТОО Б"],
            recipient=["ТОО А"],
            reference="Претензия №1",
            claim_summary=["Требуется оплатить 500 000 тенге."],
            position=[],
            objections=[],
            legal_basis=[],
            response_terms=[],
            attachments=[],
            verification_notes=[],
            source_urls=[],
        )

        async def original(_self, _context, _research, language="ru"):
            return defective

        calls: list[dict] = []

        class FakeService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                return {
                    "title": "Ответ на претензию",
                    "sender": ["ТОО Б"],
                    "recipient": ["ТОО А"],
                    "reference": "Претензия №1",
                    "claim_summary": ["Заявлено требование об оплате 500 000 тенге."],
                    "position": ["Требование не признаём по причинам, указанным ниже."],
                    "objections": ["Сумма не подтверждена актом сверки, представленным в материалах."],
                    "legal_basis": [],
                    "response_terms": ["Просим предоставить подтверждающие документы."],
                    "attachments": [],
                    "verification_notes": [],
                }

        result = await repair_pretrial_response_to_target(
            FakeService(),
            original,
            "Претензия требует оплатить 500 000 тенге; клиент оспаривает сумму.",
            _research(),
            "ru",
        )
        assert len(calls) == 1
        assert result.position
        assert result.objections

    asyncio.run(scenario())


def test_pretrial_response_repair_failure_returns_original_preliminary() -> None:
    async def scenario() -> None:
        defective = PretrialResponseDraft(
            status=VerificationStatus.NEEDS_VERIFICATION,
            title="Ответ на претензию",
            sender=["ТОО Б"],
            recipient=["ТОО А"],
            reference="Претензия №1",
            claim_summary=["Требуется оплатить 500 000 тенге."],
            position=[],
            objections=[],
            legal_basis=[],
            response_terms=[],
            attachments=[],
            verification_notes=[],
            source_urls=[],
        )

        async def original(_self, _context, _research, language="ru"):
            return defective

        class FailingService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **_kwargs):
                raise RuntimeError("malformed repair")

        result = await repair_pretrial_response_to_target(
            FailingService(),
            original,
            "Претензия требует оплатить 500 000 тенге; клиент оспаривает сумму.",
            _research(),
            "ru",
        )
        assert result is defective
        assert result.status is VerificationStatus.NEEDS_VERIFICATION
        assert result.verification_notes

    asyncio.run(scenario())
