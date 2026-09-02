from korgan.fast_professional_repair_guard import merge_repair_payload


def test_partial_repair_preserves_required_claim_fields() -> None:
    current = {
        "title": "Исковое заявление",
        "court": "Суд",
        "claimant": "Истец",
        "defendant": "Ответчик",
        "price_of_claim": "5 000 000 тенге",
        "facts": ["Факт"],
        "legal_basis": ["Норма"],
        "requests": ["Взыскать долг"],
        "attachments": ["Договор"],
        "verification_notes": ["Проверить подсудность"],
    }

    merged = merge_repair_payload(current, {"court": "Уточнённый суд"})

    assert merged["court"] == "Уточнённый суд"
    assert merged["legal_basis"] == ["Норма"]
    assert merged["requests"] == ["Взыскать долг"]
    assert merged["attachments"] == ["Договор"]
    assert merged["verification_notes"] == ["Проверить подсудность"]
