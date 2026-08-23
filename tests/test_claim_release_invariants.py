from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.claim_release_invariants import enforce_claim_release_invariants
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Иск о взыскании задолженности и договорной неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО «Поставщик», БИН 123456789012"],
        defendant=["ТОО «Покупатель», БИН 210987654321"],
        price_of_claim="12 996 000 тенге",
        facts=[
            "Ответчик не оплатил поставленный товар на сумму 12 000 000 тенге; данный факт подтвержден текстом претензии Истца.",
            "Задолженность не погашена и не опровергнута Ответчиком.",
        ],
        legal_basis=[
            "Иск должен соответствовать требованиям формы. Правовое основание: статья 148 ГПК РК.",
            "Покупатель обязан оплатить переданный товар. Правовое основание: статья 439 ГК РК (Особенная часть).",
        ],
        requests=[
            "Взыскать с ответчика основной долг в размере 12 000 000 тенге.",
            "Взыскать договорную неустойку в размере 996 000 тенге.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
        state_duty="389 880 тенге",
    )


def test_removes_article_148_and_circular_self_evidence() -> None:
    draft = _draft()

    enforce_claim_release_invariants("Договор поставки", draft)

    assert all("148" not in item for item in draft.legal_basis)
    assert any("439" in item for item in draft.legal_basis)
    facts = "\n".join(draft.facts).lower()
    assert "подтвержден текстом претензии" not in facts
    assert "не опровергнута ответчиком" not in facts
    notes = "\n".join(draft.verification_notes).lower()
    assert "банковской выпиской" in notes
    assert "актом сверки" in notes
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_removes_kazakh_article_148_from_material_basis() -> None:
    draft = _draft()
    draft.legal_basis.insert(0, "Талап нысаны туралы 148-бап АПК РК талаптары қолданылады.")

    enforce_claim_release_invariants("Шарт бойынша берешекті өндіріп алу", draft, language="kk")

    joined = "\n".join(draft.legal_basis)
    assert "148-бап" not in joined
    assert "439" in joined


def test_restores_explicit_judicial_cost_request_without_inventing_amount() -> None:
    draft = _draft()
    context = "ПРОШУ: взыскать основной долг, неустойку и судебные расходы с Ответчика."

    enforce_claim_release_invariants(context, draft)

    requests = "\n".join(draft.requests).lower()
    assert "судебные расходы" in requests
    assert requests.count("судебные расходы") == 1


def test_restores_kazakh_judicial_cost_request_without_duplication() -> None:
    draft = _draft()
    draft.requests = ["Жауапкерден негізгі берешекті өндіріп алу."]
    context = "Жауапкерден негізгі берешек пен сот шығындарын өндіріп алуды сұраймын."

    enforce_claim_release_invariants(context, draft, language="kk")
    enforce_claim_release_invariants(context, draft, language="kk")

    requests = "\n".join(draft.requests).lower()
    assert "сот шығындарын" in requests
    assert requests.count("сот шығындарын") == 1
    assert "взыскать" not in requests


def test_negated_cost_request_does_not_restore_ru_or_kk_costs() -> None:
    ru = _draft()
    ru.requests = ["Взыскать основной долг."]
    enforce_claim_release_invariants("Судебные расходы не прошу взыскивать.", ru, language="ru")
    assert not any("судебные расходы" in item.lower() for item in ru.requests)

    kk = _draft()
    kk.requests = ["Негізгі берешекті өндіріп алу."]
    enforce_claim_release_invariants("Сот шығындарын өндіріп алуды сұрамаймын.", kk, language="kk")
    assert not any("сот шығын" in item.lower() for item in kk.requests)


def test_same_day_pretrial_demand_adds_filing_action_and_downgrades() -> None:
    draft = _draft()
    today = datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")
    context = f"Досудебная претензия от {today} направлена ответчику."

    enforce_claim_release_invariants(context, draft)

    assert draft.status is VerificationStatus.NEEDS_VERIFICATION
    assert any(
        note.startswith(FILING_ACTION_PREFIX) and "досудебная претензия датирована днем" in note.lower()
        for note in draft.verification_notes
    )


def test_past_pretrial_demand_does_not_add_same_day_filing_action() -> None:
    draft = _draft()
    draft.facts = []
    draft.verification_notes = []
    context = "Досудебная претензия от 01.01.2025 направлена ответчику."

    enforce_claim_release_invariants(context, draft)

    assert not any("досудебная претензия датирована днем" in note.lower() for note in draft.verification_notes)
