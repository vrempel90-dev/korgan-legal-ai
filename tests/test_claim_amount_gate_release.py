"""AMOUNT_MISMATCH не должен блокировать корректно составленный иск.

Проверка сумм делает ready=False независимо от оценки качества, поэтому её
ложное срабатывание означает не «документ похуже», а «документа нет вовсе».
Ровно это и происходило в проде на деле KOR-95630BF72578: иск о возврате
предоплаты был написан, но не выпущен.
"""

from __future__ import annotations

from korgan.claim_quality_gate import check_amount_consistency
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft(**overrides) -> ClaimDraft:
    base = dict(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о возврате предоплаты и взыскании неустойки",
        court="Бостандыкский районный суд города Алматы",
        claimant=["Сағындықов Ержан Мұратұлы, ИИН 910317301245"],
        defendant=["ТОО «Ремонт Плюс», БИН 210540019876"],
        price_of_claim="1 512 000 тенге",
        facts=[],
        legal_basis=["Статья 953 ГК РК: подрядчик обязан вернуть неотработанный аванс (обстоятельство 1)."],
        requests=[
            "Взыскать с ответчика в пользу истца неотработанный аванс в размере 1 400 000 тенге.",
            "Взыскать с ответчика в пользу истца неустойку в размере 112 000 тенге.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )
    base.update(overrides)
    return ClaimDraft(**base)


def test_receipt_in_attachments_does_not_block_release():
    """Приложение — название доказательства, а не заявленное требование."""
    draft = _draft(
        attachments=[
            "Чек Kaspi от 05.03.2026 на 1 600 000 тенге — копия, 1 л.",
            "Выписка Kaspi с возвратом 200 000 тенге — копия, 2 л.",
        ]
    )
    assert check_amount_consistency(draft) == []


def test_contract_price_in_facts_does_not_block_release():
    """Цена договора называется в фактах, но ко взысканию не заявляется."""
    draft = _draft(
        facts=[
            "03.03.2026 стороны заключили договор подряда № 17, общая цена работ — 3 200 000 тенге.",
            "05.03.2026 истец внёс предоплату 1 600 000 тенге.",
            "12.05.2026 ответчик вернул 200 000 тенге.",
        ]
    )
    assert check_amount_consistency(draft) == []


def test_prepayment_wording_variants_are_recognised():
    """Формулировка аванса не должна решать, выпустится документ или нет."""
    for line in (
        "Истец перечислил предоплату 1 600 000 тенге платёжным поручением.",
        "Истцом внесён аванс в сумме 1 600 000 тенге.",
        "Истец оплатил 1 600 000 тенге в качестве задатка.",
        "Стоимость работ по договору составила 3 200 000 тенге.",
        "Ответчик возвратил истцу 200 000 тенге.",
    ):
        assert check_amount_consistency(_draft(facts=[line])) == [], line


def test_real_contradiction_in_facts_is_still_caught():
    """Ослабление не должно превратить сверку в бесполезную."""
    draft = _draft(
        facts=["Задолженность ответчика перед истцом составляет 9 900 000 тенге."]
    )
    issues = check_amount_consistency(draft)
    assert any("9 900 000" in issue for issue in issues)


def test_price_of_claim_must_equal_the_prayer_total():
    """Основная арифметическая сверка остаётся нетронутой."""
    draft = _draft(price_of_claim="1 000 000 тенге")
    issues = check_amount_consistency(draft)
    assert any("не равна сумме имущественных требований" in issue for issue in issues)


def test_penalty_in_title_still_requires_a_prayer_item():
    draft = _draft(
        requests=["Взыскать с ответчика в пользу истца неотработанный аванс в размере 1 512 000 тенге."]
    )
    issues = check_amount_consistency(draft)
    assert any("неустойку" in issue or "неустойк" in issue for issue in issues)
