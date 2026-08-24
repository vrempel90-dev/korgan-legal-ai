from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, pretrial_quality_issues
from korgan.provision_check import verified_claim_line
from korgan.universal_word_quality_guard import (
    repair_pretrial_to_target,
    verified_legal_basis_from_research,
)

_ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
_PROVISION = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства."
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


def test_verified_basis_projection_removes_internal_research_metadata() -> None:
    basis = verified_legal_basis_from_research(_verified_research())

    assert basis == [
        "Обязательство должно исполняться надлежащим образом (статья 272 ГК РК)."
    ]
    assert "текст нормы" not in basis[0]
    assert "источник:" not in basis[0]


def test_pretrial_repairs_bad_article_from_verified_research_without_second_llm_call() -> None:
    async def scenario() -> None:
        research = _verified_research()
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
