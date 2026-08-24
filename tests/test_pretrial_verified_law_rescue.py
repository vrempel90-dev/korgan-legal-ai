from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.kazakh_article_forms import install_kazakh_article_forms
from korgan.kazakh_legal_bridge import install_kazakh_legal_bridge
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, pretrial_quality_issues
from korgan.pretrial_response import PretrialResponseDraft, pretrial_response_quality_issues
from korgan.provision_check import verified_claim_line
from korgan.universal_word_quality_guard import (
    repair_pretrial_response_to_target,
    repair_pretrial_to_target,
    verified_legal_basis_from_research,
)

_ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
_GPK_ADILET = "https://adilet.zan.kz/rus/docs/K1500000377"
_TK_ADILET = "https://adilet.zan.kz/rus/docs/K1500000414"
_PROVISION = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства."
)
_GPK_PROVISION = (
    "В исковом заявлении должны быть указаны обстоятельства, на которых истец основывает "
    "свои требования, а также доказательства, подтверждающие эти обстоятельства."
)
_TK_PROVISION = (
    "Работодатель обязан соблюдать требования трудового законодательства Республики Казахстан "
    "и условия заключенного трудового договора."
)


def _verified_research() -> LegalResearch:
    claim = verified_claim_line(
        "Обязательство должно исполняться надлежащим образом.",
        "статья 272 ГК РК",
        _PROVISION,
        _ADILET,
    )
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[claim],
        unverified_claims=[],
        source_urls=[_ADILET],
        notes=[],
    )


def _verified_research_with_cross_act_noise() -> LegalResearch:
    research = _verified_research()
    research.verified_claims.extend(
        [
            verified_claim_line(
                "Исковое заявление должно содержать обстоятельства и подтверждающие их доказательства.",
                "статья 148 ГПК РК",
                _GPK_PROVISION,
                _GPK_ADILET,
            ),
            verified_claim_line(
                "Работодатель обязан соблюдать требования трудового законодательства.",
                "статья 23 ТК РК",
                _TK_PROVISION,
                _TK_ADILET,
            ),
        ]
    )
    research.source_urls.extend([_GPK_ADILET, _TK_ADILET])
    return research


def _verified_research_kk() -> LegalResearch:
    claim = verified_claim_line(
        "Міндеттеме тиісті түрде орындалуға тиіс.",
        "статья 272 ГК РК",
        _PROVISION,
        _ADILET,
    )
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[claim],
        unverified_claims=[],
        source_urls=[_ADILET],
        notes=[],
    )


def _draft_with_bad_article() -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Досудебная претензия",
        sender=["ТОО «Арман Снабжение»"],
        recipient=["ТОО «Вектор Строй»"],
        facts=["Товар поставлен, однако покупатель оплату не произвел."],
        legal_basis=["Согласно статье 9999 ГК РК покупатель обязан немедленно оплатить задолженность."],
        demands=["Требуем оплатить основной долг в размере 4 800 000 тенге."],
        deadline="в срок, предусмотренный договором",
        consequences=["При неисполнении требования поставщик вправе обратиться в суд."],
        attachments=["Копия договора", "Копия накладной"],
        verification_notes=[],
        source_urls=[_ADILET],
    )


def _draft_with_bad_article_kk() -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Сотқа дейінгі талап",
        sender=["«Арман Снабжение» ЖШС"],
        recipient=["«Вектор Строй» ЖШС"],
        facts=["Тауар жеткізілді, алайда сатып алушы төлем жасамады."],
        legal_basis=["ҚР АК 9999-бабы бойынша сатып алушы берешекті дереу төлеуге міндетті."],
        demands=["4 800 000 теңге негізгі берешекті төлеуді талап етеміз."],
        deadline="шартта көзделген мерзімде",
        consequences=["Талап орындалмаған жағдайда жеткізуші сотқа жүгінуге құқылы."],
        attachments=["Шарттың көшірмесі", "Жүкқұжаттың көшірмесі"],
        verification_notes=[],
        source_urls=[_ADILET],
    )


def _response_with_bad_article() -> PretrialResponseDraft:
    return PretrialResponseDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Ответ на досудебную претензию",
        sender=["ТОО «Вектор Строй»"],
        recipient=["ТОО «Арман Снабжение»"],
        reference="Претензия по договору поставки",
        claim_summary=["Заявлено требование об оплате задолженности."],
        position=["Требование рассматривается в подтвержденной материалами части."],
        objections=["Размер требования подлежит сверке по первичным документам."],
        legal_basis=["Согласно статье 9999 ГК РК обязательство считается прекращенным автоматически."],
        response_terms=["Предлагаем провести сверку документов и расчетов."],
        attachments=["Копии имеющихся первичных документов"],
        verification_notes=[],
        source_urls=[_ADILET],
    )


def test_verified_basis_projection_removes_internal_research_metadata() -> None:
    basis = verified_legal_basis_from_research(_verified_research())
    assert basis == ["Обязательство должно исполняться надлежащим образом (статья 272 ГК РК)."]
    assert "текст нормы" not in basis[0]
    assert "источник:" not in basis[0]


def test_verified_basis_projection_localizes_kazakh_article_label() -> None:
    basis = verified_legal_basis_from_research(_verified_research_kk(), language="kk")

    assert basis == ["Міндеттеме тиісті түрде орындалуға тиіс (ҚР АК 272-бабы)."]
    assert "статья 272" not in basis[0].lower()


def test_pretrial_repairs_bad_article_from_same_verified_act_without_second_llm_call() -> None:
    async def scenario() -> None:
        research = _verified_research_with_cross_act_noise()
        initial = _draft_with_bad_article()
        assert pretrial_quality_issues(initial, research)
        calls: list[dict] = []

        async def original(_self, _context, _research, language="ru"):
            return initial

        class FakeService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                repaired = _draft_with_bad_article()
                return {
                    "title": repaired.title,
                    "sender": repaired.sender,
                    "recipient": repaired.recipient,
                    "facts": repaired.facts,
                    "legal_basis": repaired.legal_basis,
                    "demands": repaired.demands,
                    "deadline": repaired.deadline,
                    "consequences": repaired.consequences,
                    "attachments": repaired.attachments,
                    "verification_notes": [],
                }

        result = await repair_pretrial_to_target(
            FakeService(),
            original,
            "Поставка на 4 800 000 тенге исполнена, оплата просрочена.",
            research,
            "ru",
        )
        assert len(calls) == 1
        rendered_law = "\n".join(result.legal_basis)
        assert "9999" not in rendered_law
        assert "статья 272 ГК РК" in rendered_law
        assert "ГПК РК" not in rendered_law
        assert "ТК РК" not in rendered_law
        assert pretrial_quality_issues(result, research) == []
        assert result.status is VerificationStatus.VERIFIED

    asyncio.run(scenario())


def test_pretrial_response_repairs_bad_article_from_same_verified_act_without_second_llm_call() -> None:
    async def scenario() -> None:
        research = _verified_research_with_cross_act_noise()
        initial = _response_with_bad_article()
        assert pretrial_response_quality_issues(initial, research)
        calls: list[dict] = []

        async def original(_self, _context, _research, language="ru"):
            return initial

        class FakeService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                repaired = _response_with_bad_article()
                return {
                    "title": repaired.title,
                    "sender": repaired.sender,
                    "recipient": repaired.recipient,
                    "reference": repaired.reference,
                    "claim_summary": repaired.claim_summary,
                    "position": repaired.position,
                    "objections": repaired.objections,
                    "legal_basis": repaired.legal_basis,
                    "response_terms": repaired.response_terms,
                    "attachments": repaired.attachments,
                    "verification_notes": [],
                }

        result = await repair_pretrial_response_to_target(
            FakeService(),
            original,
            "Получена претензия по договору поставки; требуется подготовить мотивированный ответ.",
            research,
            "ru",
        )
        assert len(calls) == 1
        rendered_law = "\n".join(result.legal_basis)
        assert "9999" not in rendered_law
        assert "статья 272 ГК РК" in rendered_law
        assert "ГПК РК" not in rendered_law
        assert "ТК РК" not in rendered_law
        assert pretrial_response_quality_issues(result, research) == []
        assert result.status is VerificationStatus.VERIFIED

    asyncio.run(scenario())


def test_pretrial_kazakh_rescue_releases_verified_document() -> None:
    async def scenario() -> None:
        install_kazakh_legal_bridge()
        install_kazakh_article_forms()
        research = _verified_research_kk()
        initial = _draft_with_bad_article_kk()
        assert pretrial_quality_issues(initial, research)
        calls: list[dict] = []

        async def original(_self, _context, _research, language="kk"):
            return initial

        class FakeService:
            settings = SimpleNamespace(max_case_text_chars=20_000)

            async def _quality_repair(self, **kwargs):
                calls.append(kwargs)
                repaired = _draft_with_bad_article_kk()
                return {
                    "title": repaired.title,
                    "sender": repaired.sender,
                    "recipient": repaired.recipient,
                    "facts": repaired.facts,
                    "legal_basis": repaired.legal_basis,
                    "demands": repaired.demands,
                    "deadline": repaired.deadline,
                    "consequences": repaired.consequences,
                    "attachments": repaired.attachments,
                    "verification_notes": [],
                }

        result = await repair_pretrial_to_target(
            FakeService(),
            original,
            "Тауар жеткізілді, төлем мерзімі өтті.",
            research,
            "kk",
        )
        assert len(calls) == 1
        rendered_law = "\n".join(result.legal_basis)
        assert "9999" not in rendered_law
        assert "ҚР АК 272-бабы" in rendered_law
        assert "статья 272" not in rendered_law.lower()
        assert pretrial_quality_issues(result, research) == []
        assert result.status is VerificationStatus.VERIFIED

    asyncio.run(scenario())


def test_verified_basis_projection_fails_closed_without_source_bound_claims() -> None:
    research = LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=["Норма не подтверждена."],
        source_urls=[],
        notes=[],
    )
    assert verified_legal_basis_from_research(research) == []
