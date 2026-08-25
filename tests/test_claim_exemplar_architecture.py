from __future__ import annotations

from korgan.claim_exemplar_architecture import architecture_block, architecture_issues, detect_architecture
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[], procedural_requirements=[], verified_claims=[], unverified_claims=[], source_urls=[], notes=[]
    )


def _draft(**overrides) -> ClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        source_urls=[],
        title="И С К\nо взыскании задолженности и неустойки",
        court="Суд",
        claimant=["Истец"], defendant=["Ответчик"], price_of_claim="5 016 000 тенге",
        state_duty="150 480 тенге",
        late_interest="",
        facts=["Ответчик допустил просрочку оплаты."],
        legal_basis=["Неустойка подлежит взысканию согласно подтвержденной норме."],
        requests=["Взыскать основной долг 4 800 000 тенге."],
        attachments=["Договор", "Накладная"], verification_notes=[],
    )
    data.update(overrides)
    return ClaimDraft(**data)


def test_detects_supply_and_work_architecture() -> None:
    assert detect_architecture("договор поставки, покупатель не оплатил").code == "supply"
    assert detect_architecture("договор подряда, акт выполненных монтажных работ").code == "work"


def test_architecture_is_reasoning_not_source_of_facts_or_law() -> None:
    text = architecture_block("договор поставки")
    assert "не источник фактов" in text.lower()
    assert "не источник права" in text.lower()
    assert "ФАКТЫ -> ДОКАЗАТЕЛЬСТВА -> НОРМЫ -> РАСЧЕТЫ -> ПРОШУ СУД -> ПРИЛОЖЕНИЯ" in text


def test_missing_penalty_and_state_duty_in_petitum_are_blockers() -> None:
    issues = architecture_issues("Прошу взыскать долг и пеню по договору поставки.", _research(), _draft())
    assert any("неустойку/пеню" in x for x in issues)
    assert any("госпошлины" in x for x in issues)


def test_irrelevant_branch_norm_is_rejected_without_anchor() -> None:
    draft = _draft(
        legal_basis=["По статье 30 ГПК РК иск по деятельности филиала может быть предъявлен по месту филиала."],
        requests=["Взыскать долг.", "Взыскать государственную пошлину 150 480 тенге."],
    )
    issues = architecture_issues("Ответчик ТОО, адрес в Астане.", _research(), draft)
    assert any("филиале/представительстве" in x for x in issues)


def test_branch_norm_allowed_when_case_has_branch_fact() -> None:
    draft = _draft(
        legal_basis=["Спор возник из деятельности филиала ответчика."],
        requests=["Взыскать долг.", "Взыскать государственную пошлину 150 480 тенге."],
    )
    issues = architecture_issues("Спор возник из деятельности филиала ответчика.", _research(), draft)
    assert not any("филиале/представительстве" in x for x in issues)


def test_hedging_formula_is_rejected() -> None:
    draft = _draft(
        legal_basis=["Неустойка начисляется до решения суда или платежа, в зависимости от того, что наступит ранее."],
        requests=["Взыскать пеню.", "Взыскать государственную пошлину 150 480 тенге."],
    )
    issues = architecture_issues("Прошу взыскать пеню.", _research(), draft)
    assert any("хеджирующую" in x for x in issues)
