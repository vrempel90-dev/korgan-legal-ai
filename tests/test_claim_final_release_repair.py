from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan import bot as base_bot
from korgan.claim_release_repair import _client_block_message, repair_claim_release
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


class _Finding:
    def __init__(self, note: str) -> None:
        self.note = note

    def as_note(self) -> str:
        return self.note


class _RepairService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.settings = SimpleNamespace(max_case_text_chars=12000)

    async def _quality_repair(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "title": "Исковое заявление о взыскании денежных средств",
            "court": "",
            "claimant": ["Истец: Иванов Иван"],
            "defendant": ["Ответчик: ТОО «Исполнитель»"],
            "price_of_claim": "500 000 тенге",
            "facts": [
                "Истец оплатил 500 000 тенге по договору.",
                "Ответчик обязательство в согласованный срок не исполнил.",
                "Денежные средства не возвращены.",
            ],
            "legal_basis": [
                "Обязательство подлежит надлежащему исполнению согласно статье 272 ГК РК."
            ],
            "requests": ["Взыскать с ответчика 500 000 тенге."],
            "attachments": ["Договор", "Документ об оплате"],
            "verification_notes": [],
        }


class _Adapter:
    def __init__(self, inner) -> None:
        self.inner = inner


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Обязательства должны исполняться надлежащим образом "
            "[основание: статья 272 ГК РК; текст нормы: «Обязательства должны исполняться надлежащим образом в соответствии с условиями обязательства и требованиями законодательства.»; источник: https://adilet.zan.kz/rus/docs/K940001000_]"
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K940001000_"],
        notes=[],
    )


def _bad_draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление",
        court="",
        claimant=["Истец: Иванов Иван"],
        defendant=["Ответчик: ТОО «Исполнитель»"],
        price_of_claim="500 000 тенге",
        state_duty="",
        facts=[
            "Истец оплатил 500 000 тенге по договору.",
            "Ответчик обязательство не исполнил.",
            "Денежные средства не возвращены.",
        ],
        legal_basis=[
            "Статья 163 ГПК РК требует приложить подтверждение соблюдения закона."
        ],
        requests=["Взыскать с ответчика 500 000 тенге."],
        attachments=["Договор", "Документ об оплате"],
        verification_notes=[],
        source_urls=[],
    )


def test_final_release_blocker_gets_one_verified_only_repair(monkeypatch) -> None:
    service = _RepairService()
    monkeypatch.setattr(base_bot, "service", _Adapter(service))
    release = SimpleNamespace(
        citations=SimpleNamespace(
            blocking=[
                _Finding(
                    "статья 163 ГПК РК: пересказ вводит требование «закон», которого нет в тексте нормы"
                )
            ]
        ),
        integrity=[],
    )

    repaired = asyncio.run(
        repair_claim_release(
            context=(
                "Истец оплатил 500 000 тенге по договору. Ответчик обязательство не исполнил. "
                "Истец просит взыскать 500 000 тенге."
            ),
            research=_research(),
            draft=_bad_draft(),
            language="ru",
            release=release,
        )
    )

    assert repaired is not None
    assert len(service.calls) == 1
    issues = service.calls[0]["issues"]
    assert any("FINAL_RELEASE_CITATION" in item for item in issues)
    assert any("статья 163 ГПК РК" in item for item in issues)
    assert not any("163" in item for item in repaired.legal_basis)
    assert any("272" in item for item in repaired.legal_basis)
    assert repaired.requests == ["Взыскать с ответчика 500 000 тенге."]


def test_persistent_block_message_does_not_leak_generated_draft() -> None:
    release = SimpleNamespace(
        citations=SimpleNamespace(
            blocking=[_Finding("статья 163 ГПК РК: неподтвержденный пересказ")]
        ),
        integrity=[],
    )
    message = _client_block_message(release, "ru")

    assert "не удалось безопасно исправить" in message.lower()
    assert "word" in message.lower()
    assert "Исковое заявление" not in message
    assert "ПРОШУ СУД" not in message
    assert "статья 163" not in message.lower()
