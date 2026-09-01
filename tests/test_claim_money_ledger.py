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
        "Взыскать расходы на оплату услуг представителя 75 000 тенге.",
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


def test_wrong_explicit_total_fails_closed_instead_of_becoming_claim_price():
    request = "Взыскать основной долг 1 000 000 тенге и неустойку 200 000 тенге, итого 1 500 000 тенге."
    ledger = build_claim_money_ledger([request])
    assert ledger.total == 0
    assert ledger.unresolved_requests == [request]


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


def test_arithmetic_total_after_equals_is_authoritative_when_math_matches():
    ledger = build_claim_money_ledger([
        "Взыскать 12 000 000 тенге + 996 000 тенге = 12 996 000 тенге."
    ])
    assert ledger.unresolved_requests == []
    assert ledger.total == 12_996_000


def test_wrong_arithmetic_after_equals_fails_closed():
    request = "Взыскать 1 000 000 тенге + 200 000 тенге = 1 500 000 тенге."
    ledger = build_claim_money_ledger([request])
    assert ledger.unresolved_requests == [request]


def test_monetary_alternative_relief_fails_closed_instead_of_being_silently_dropped():
    request = "В качестве альтернативного требования взыскать стоимость имущества 800 000 тенге."
    ledger = build_claim_money_ledger([request])
    assert ledger.total == 0
    assert ledger.unresolved_requests == [request]


def test_malformed_grouping_fails_closed_instead_of_becoming_the_claim_price():
    """«12 34 567 тенге» — не сумма, и ценой иска она стать не вправе.

    У реестра была своя мягкая регулярка суммы, которая просто вырезала пробелы
    и читала кривую группировку как 1 234 567. Канонический парсер такую запись
    отвергает, поэтому цена иска и госпошлина считались от числа, которого в
    просительной части нет.
    """
    request = "Взыскать с ответчика основной долг 12 34 567 тенге."
    ledger = build_claim_money_ledger([request])

    assert ledger.components == []
    assert ledger.total == 0
    assert ledger.unresolved_requests == [request]


def test_malformed_grouping_next_to_a_valid_amount_fails_closed():
    request = "Взыскать основной долг 1 200 000 тенге и неустойку 1234 567 тенге."
    ledger = build_claim_money_ledger([request])

    assert ledger.total == 0
    assert ledger.unresolved_requests == [request]


def test_two_valid_components_survive_canonical_parsing():
    ledger = build_claim_money_ledger([
        "Взыскать основной долг 2 300 000 тенге и неустойку 377 200 тенге."
    ])

    assert ledger.unresolved_requests == []
    assert [item.kind for item in ledger.components] == ["principal", "penalty"]
    assert ledger.total == 2_677_200
