from __future__ import annotations

from korgan.claim_exemplar_architecture import (
    _rebuild_repaired_draft,
    architecture_block,
    architecture_issues,
    detect_architecture,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Заказчик обязан оплатить принятый результат работ. [основание: статья 623 ГК РК; источник: https://adilet.zan.kz/]",
            "Неустойка взыскивается при подтвержденном договорном основании. [основание: статья 293 ГК РК; источник: https://adilet.zan.kz/]",
            "Иск к юридическому лицу предъявляется по месту нахождения ответчика. [основание: статья 29 ГПК РК; источник: https://adilet.zan.kz/]",
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/"],
        notes=[],
    )


def _draft(**overrides) -> ClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        source_urls=["https://adilet.zan.kz/"],
        title="И С К\nо взыскании задолженности и неустойки",
        court="Специализированный межрайонный экономический суд города Астана",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="5 016 000 тенге",
        state_duty="150 480 тенге",
        late_interest="",
        facts=["Ответчик допустил просрочку оплаты."],
        legal_basis=["Статья 623 ГК РК предусматривает обязанность оплатить принятый результат работ."],
        requests=["Взыскать основной долг 4 800 000 тенге."],
        attachments=["Договор", "Акт выполненных работ"],
        verification_notes=[],
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
    assert "явно запрошенное" in text.lower()
    assert "сам расчет госпошлины не является фактом ее уплаты" in text.lower()


def test_requested_penalty_cannot_be_repaired_by_deletion() -> None:
    issues = architecture_issues(
        "Составь иск о взыскании задолженности и договорной пени по договору подряда.",
        _research(),
        _draft(),
    )
    assert any("явно просит взыскать неустойку/пеню" in x.lower() for x in issues)


def test_civil_claim_cannot_keep_only_procedural_law() -> None:
    draft = _draft(
        legal_basis=["Статья 27 ГПК РК регулирует компетенцию суда."],
        requests=["Взыскать основной долг 4 800 000 тенге."],
    )
    issues = architecture_issues("Договор подряда. Взыскать задолженность.", _research(), draft)
    assert any("материальную норму" in x.lower() for x in issues)


def test_state_duty_calculation_alone_is_not_treated_as_payment_fact() -> None:
    issues = architecture_issues(
        "Рассчитай государственную пошлину. Договор подряда, взыскать задолженность.",
        _research(),
        _draft(requests=["Взыскать основной долг 4 800 000 тенге."]),
    )
    assert not any("уплату госпошлины" in x.lower() for x in issues)
    assert not any("возмещении этого судебного расхода" in x.lower() for x in issues)


def test_paid_state_duty_must_reach_petitum() -> None:
    issues = architecture_issues(
        "Государственная пошлина оплачена, квитанция приложена. Договор подряда, взыскать задолженность.",
        _research(),
        _draft(requests=["Взыскать основной долг 4 800 000 тенге."]),
    )
    assert any("уплату госпошлины" in x.lower() for x in issues)


def test_irrelevant_branch_norm_is_rejected_without_anchor() -> None:
    draft = _draft(
        legal_basis=[
            "Статья 623 ГК РК предусматривает обязанность оплатить результат работ.",
            "По статье 30 ГПК РК иск по деятельности филиала может быть предъявлен по месту филиала.",
            "Статья 29 ГПК РК определяет территориальную подсудность по месту ответчика.",
        ],
    )
    issues = architecture_issues("Ответчик ТОО, место нахождения — Астана.", _research(), draft)
    assert any("филиале/представительстве" in x for x in issues)


def test_verified_ordinary_venue_cannot_disappear() -> None:
    draft = _draft(
        legal_basis=["Статья 623 ГК РК предусматривает обязанность оплатить результат работ."],
    )
    issues = architecture_issues("Ответчик ТОО находится в Астане. Договор подряда.", _research(), draft)
    assert any("территориальной подсудности" in x.lower() for x in issues)


def test_branch_norm_allowed_when_case_has_branch_fact() -> None:
    research = _research()
    draft = _draft(
        legal_basis=[
            "Статья 623 ГК РК предусматривает обязанность оплатить результат работ.",
            "Спор возник из деятельности филиала ответчика.",
            "Статья 29 ГПК РК определяет территориальную подсудность по месту ответчика.",
        ],
    )
    issues = architecture_issues("Спор возник из деятельности филиала ответчика.", research, draft)
    assert not any("филиале/представительстве" in x for x in issues)


def test_hedging_formula_is_rejected() -> None:
    draft = _draft(
        legal_basis=[
            "Статья 623 ГК РК предусматривает обязанность оплатить результат работ.",
            "Статья 29 ГПК РК определяет территориальную подсудность по месту ответчика.",
            "Неустойка начисляется до решения суда или платежа, в зависимости от того, что наступит ранее.",
        ],
        requests=["Взыскать пеню."],
    )
    issues = architecture_issues("Прошу взыскать пеню по договору подряда.", _research(), draft)
    assert any("хеджирующую" in x for x in issues)


def test_architecture_repair_preserves_deterministic_money_and_verified_material_law() -> None:
    original = _draft(
        late_interest="Расчет по статье 353: 216 000 тенге.",
        legal_basis=[
            "Статья 623 ГК РК предусматривает обязанность оплатить результат работ.",
            "Статья 29 ГПК РК определяет территориальную подсудность по месту ответчика.",
        ],
    )
    payload = {
        "title": original.title,
        "court": original.court,
        "claimant": original.claimant,
        "defendant": original.defendant,
        "price_of_claim": original.price_of_claim,
        "facts": original.facts,
        "legal_basis": ["Статья 27 ГПК РК регулирует компетенцию суда."],
        "requests": original.requests,
        "attachments": original.attachments,
        "verification_notes": [],
    }
    repaired = _rebuild_repaired_draft("Договор подряда. Ответчик находится в Астане.", _research(), original, payload)
    assert repaired.state_duty == "150 480 тенге"
    assert repaired.late_interest == "Расчет по статье 353: 216 000 тенге."
    assert any("623" in line for line in repaired.legal_basis)
    assert any("29" in line for line in repaired.legal_basis)
