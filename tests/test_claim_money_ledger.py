from korgan.claim_money_ledger import build_claim_money_ledger


def test_explicit_total_is_not_double_counted():
    ledger = build_claim_money_ledger([
        "Взыскать основной долг 12 000 000 тенге и неустойку 996 000 тенге, итого 12 996 000 тенге."
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 12_996_000
    assert len(ledger.components) == 1
    assert ledger.components[0].kind == "total"


def test_separate_independent_property_requests_are_summed():
    ledger = build_claim_money_ledger([
        "Взыскать основной долг 12 000 000 тенге.",
        "Взыскать неустойку 996 000 тенге.",
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 12_996_000
    assert {item.kind for item in ledger.components} == {"principal", "penalty"}


def test_same_line_independent_components_bind_to_nearest_labels():
    ledger = build_claim_money_ledger([
        "Взыскать основной долг 12 000 000 тенге и неустойку 996 000 тенге."
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 12_996_000
    assert [item.kind for item in ledger.components] == ["principal", "penalty"]


def test_state_duty_and_court_costs_do_not_enter_claim_price():
    ledger = build_claim_money_ledger([
        "Взыскать задолженность 1 000 000 тенге.",
        "Взыскать государственную пошлину 30 000 тенге.",
        "Взыскать судебные расходы на представителя 150 000 тенге.",
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 1_000_000


def test_moral_damage_amount_is_nonproperty_and_excluded_from_claim_price():
    ledger = build_claim_money_ledger([
        "Взыскать задолженность 1 000 000 тенге.",
        "Взыскать компенсацию морального вреда 200 000 тенге.",
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 1_000_000
    assert len(ledger.nonproperty_money_components) == 1
    assert ledger.nonproperty_money_components[0].kind == "moral_damage"


def test_prose_total_mixing_debt_and_moral_damage_does_not_inflate_claim_price():
    ledger = build_claim_money_ledger([
        "Взыскать основной долг 1 000 000 тенге и моральный вред 200 000 тенге, итого 1 200 000 тенге."
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 1_000_000
    assert any(item.kind == "moral_damage" and not item.included_in_claim_price for item in ledger.components)


def test_duplicate_prayer_line_is_counted_once():
    request = "Взыскать задолженность 2 300 000 тенге."
    ledger = build_claim_money_ledger([request, request])

    assert ledger.unresolved_requests == []
    assert ledger.total == 2_300_000
    assert len(ledger.components) == 1


def test_ambiguous_multi_amount_request_fails_closed():
    request = "Взыскать с ответчика 1 000 000 тенге и 250 000 тенге."
    ledger = build_claim_money_ledger([request])

    assert ledger.total == 0
    assert ledger.unresolved_requests == [request]


def test_arithmetic_total_after_equals_is_authoritative():
    ledger = build_claim_money_ledger([
        "Взыскать 12 000 000 тенге + 996 000 тенге = 12 996 000 тенге."
    ])

    assert ledger.unresolved_requests == []
    assert ledger.total == 12_996_000
