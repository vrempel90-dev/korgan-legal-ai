from __future__ import annotations

import korgan.senior_claim_preflight as senior_claim_preflight
from korgan.claim_consistency_guard import claim_consistency_errors
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


def _draft(*, legal_basis: list[str], requests: list[str]) -> ClaimDraft:
    """Build a minimal claim for deterministic consistency tests."""
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной суммы, неустойки и судебных расходов",
        court="",
        claimant=["Истец"],
        defendant=["ИП Ответчик"],
        price_of_claim="1 200 000 тенге",
        facts=[
            "Истец полностью оплатил 1 200 000 тенге.",
            "Ответчик не изготовил и не установил кухонный гарнитур в установленный договором срок.",
        ],
        legal_basis=legal_basis,
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _research() -> LegalResearch:
    """Return an empty research object for integration-only preflight tests."""
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def test_explicit_penalty_and_costs_cannot_disappear_from_prayer() -> None:
    context = (
        "Я полностью оплатил работы. Ответчик нарушил срок изготовления и установки кухни. "
        "Прошу взыскать 1 200 000 тенге, неустойку и судебные расходы."
    )
    draft = _draft(
        legal_basis=["Исполнитель отвечает за нарушение срока выполнения работы."],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error and "нет в разделе" in error for error in errors)


def test_multiline_explicit_penalty_and_costs_cannot_disappear() -> None:
    context = (
        "Я полностью оплатил работы. Ответчик нарушил срок выполнения.\n"
        "Прошу взыскать:\n- 1 200 000 тенге;\n- неустойку;\n- судебные расходы."
    )
    draft = _draft(
        legal_basis=["Исполнитель отвечает за нарушение срока выполнения работы."],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error and "нет в разделе" in error for error in errors)


def test_declined_penalty_is_not_treated_as_requested() -> None:
    context = "Не прошу взыскивать неустойку. Прошу взыскать только основной долг 1 200 000 тенге."
    draft = _draft(
        legal_basis=["Обязательство подлежит исполнению."],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert not any("неустойку/пеню" in error and "исчезло" in error for error in errors)


def test_buyer_nonpayment_rule_is_blocked_when_claimant_paid_in_full() -> None:
    context = (
        "Истец полностью оплатил 1 200 000 тенге. "
        "Ответчик не изготовил и не установил кухню в срок. Прошу вернуть уплаченную сумму."
    )
    draft = _draft(
        legal_basis=[
            "В случаях, когда договором предусмотрена предварительная оплата товара, "
            "неоплата покупателем в установленный срок признается отказом покупателя от исполнения договора."
        ],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("истец оплатил полностью" in error and "другой фактической ситуации" in error for error in errors)


def test_goods_return_penalty_rule_is_blocked_for_delayed_work() -> None:
    context = (
        "Ответчик должен был выполнить работы по изготовлению и установке кухни до 10 июля, но срок нарушил. "
        "Прошу взыскать неустойку."
    )
    draft = _draft(
        legal_basis=[
            "За просрочку требований потребителя об обмене или возврате товара надлежащего качества, "
            "а также требований при продаже товара ненадлежащего качества выплачивается неустойка 1% стоимости товара."
        ],
        requests=["Взыскать неустойку 120 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("просрочке выполнения работы/услуги" in error and "возврате/качестве товара" in error for error in errors)


def test_work_delay_penalty_basis_is_not_misclassified_as_goods_rule() -> None:
    context = (
        "Ответчик нарушил срок выполнения работы по изготовлению и установке кухни. "
        "Прошу взыскать неустойку."
    )
    draft = _draft(
        legal_basis=[
            "За нарушение сроков начала и окончания выполнения работы исполнитель обязан уплатить "
            "неустойку в размере одного процента стоимости работы за каждый день просрочки."
        ],
        requests=["Взыскать неустойку 120 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert not any("возврате/качестве товара" in error for error in errors)


def test_penalty_without_amount_cannot_be_filing_ready() -> None:
    context = "Прошу взыскать неустойку за нарушение срока выполнения работ."
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать с Ответчика неустойку."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("без конкретного размера" in error for error in errors)


def test_principal_amount_does_not_satisfy_separate_penalty_amount() -> None:
    context = "Прошу взыскать 1 200 000 тенге и неустойку за нарушение срока выполнения работ."
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать с Ответчика 1 200 000 тенге.", "Взыскать с Ответчика неустойку."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("без конкретного размера" in error for error in errors)


def test_calculated_penalty_cannot_disappear_from_prayer() -> None:
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать с Ответчика основной долг 1 200 000 тенге."],
    )
    draft.title = "Исковое заявление о взыскании задолженности"
    draft.calculation = [
        "Основной долг: 1 200 000 тенге.",
        "Договорная неустойка: 120 000 тенге; база: 1 200 000 тенге; ставка: 1% за день; дней: 10.",
        "Итого цена иска: 1 320 000 тенге.",
    ]
    draft.price_of_claim = "1 200 000 тенге"

    errors = claim_consistency_errors("Ответчик нарушил срок выполнения работ.", draft)

    assert any(
        "расчёте" in error and "неустойк" in error.lower() and "ПРОШУ СУД" in error
        for error in errors
    )


def test_prayer_penalty_cannot_be_absent_from_structured_calculation() -> None:
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=[
            "Взыскать с Ответчика основной долг 1 200 000 тенге.",
            "Взыскать с Ответчика договорную неустойку 120 000 тенге.",
        ],
    )
    draft.calculation = ["Основной долг: 1 200 000 тенге."]
    draft.price_of_claim = "1 320 000 тенге"

    errors = claim_consistency_errors("Ответчик нарушил срок выполнения работ.", draft)

    assert any(
        "ПРОШУ СУД" in error and "неустойк" in error.lower() and "расчёте" in error
        for error in errors
    )


def test_penalty_amount_must_match_between_calculation_and_prayer() -> None:
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=[
            "Взыскать с Ответчика основной долг 1 200 000 тенге.",
            "Взыскать с Ответчика договорную неустойку 120 000 тенге.",
        ],
    )
    draft.calculation = [
        "Основной долг: 1 200 000 тенге.",
        "Договорная неустойка: 100 000 тенге.",
        "Итого цена иска: 1 300 000 тенге.",
    ]
    draft.price_of_claim = "1 320 000 тенге"

    errors = claim_consistency_errors("Ответчик нарушил срок выполнения работ.", draft)

    assert any(
        "неустойк" in error.lower() and "100 000" in error and "120 000" in error
        for error in errors
    )


def test_malformed_penalty_amount_cannot_satisfy_reconciliation() -> None:
    """Сверка использует канонический парсер, а не собственную «мягкую» регулярку.

    «12 34 567 тенге» — не сумма: разряды разбиты неверно, и цена иска с
    госпошлиной такое значение читать откажутся. Сверка расчёта с просительной
    частью не вправе считать такую строку подтверждённым размером неустойки.
    """
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=[
            "Взыскать с Ответчика основной долг 1 200 000 тенге.",
            "Взыскать с Ответчика договорную неустойку 12 34 567 тенге.",
        ],
    )
    draft.calculation = [
        "Основной долг: 1 200 000 тенге.",
        "Договорная неустойка: 120 000 тенге.",
    ]
    draft.price_of_claim = "1 320 000 тенге"

    errors = claim_consistency_errors("Ответчик нарушил срок выполнения работ.", draft)

    assert not any("12 34 567" in error for error in errors)
    assert not any("34 567" in error for error in errors)


def _duty_draft(*, state_duty: str, facts: list[str] | None = None, attachments: list[str] | None = None) -> ClaimDraft:
    """Иск, у которого госпошлина уже посчитана детерминированным кодом."""
    draft = _draft(
        legal_basis=["Обязанность оплатить принятый товар."],
        requests=["Взыскать с Ответчика основной долг 12 000 000 тенге."],
    )
    draft.title = "Исковое заявление о взыскании задолженности"
    draft.price_of_claim = "12 000 000 тенге"
    draft.facts = facts if facts is not None else ["Долг 12 000 000 тенге не оплачен."]
    draft.attachments = attachments or []
    draft.state_duty = state_duty
    return draft


def test_model_state_duty_cannot_contradict_the_deterministic_value() -> None:
    """Размер госпошлины определяет детерминированный код, а не текст модели.

    Если документ где-то называет другую сумму пошлины, суд вернёт иск как
    оплаченный не полностью, а истец узнает об этом уже после подачи.
    """
    draft = _duty_draft(
        state_duty="360 000 тенге (3% от цены иска; максимум 20 000 МРП; статья 665 Налогового кодекса РК)",
        facts=[
            "Долг 12 000 000 тенге не оплачен.",
            "Государственная пошлина составляет 120 000 тенге.",
        ],
    )

    errors = claim_consistency_errors("ТОО против ТОО, долг 12 000 000 тенге.", draft)

    assert any("пошлин" in error.lower() and "120 000" in error and "360 000" in error for error in errors)


def test_paid_duty_in_attachments_must_match_the_deterministic_value() -> None:
    draft = _duty_draft(
        state_duty="360 000 тенге (3% от цены иска; максимум 20 000 МРП; статья 665 Налогового кодекса РК)",
        attachments=["Квитанция об уплате государственной пошлины на 120 000 тенге."],
    )

    errors = claim_consistency_errors("ТОО против ТОО, долг 12 000 000 тенге.", draft)

    assert any("пошлин" in error.lower() and "120 000" in error for error in errors)


def test_matching_duty_amount_is_not_reported() -> None:
    draft = _duty_draft(
        state_duty="360 000 тенге (3% от цены иска; максимум 20 000 МРП; статья 665 Налогового кодекса РК)",
        attachments=["Квитанция об уплате государственной пошлины на 360 000 тенге."],
    )
    draft.requests.append(
        "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере 360 000 тенге."
    )

    errors = claim_consistency_errors("ТОО против ТОО, долг 12 000 000 тенге.", draft)

    assert not any("пошлин" in error.lower() for error in errors)


def test_undetermined_duty_does_not_produce_a_false_conflict() -> None:
    """Пока детерминированного значения нет, сверять не с чем — молчим."""
    draft = _duty_draft(
        state_duty="[ТРЕБУЕТ РАСЧЁТА]",
        attachments=["Квитанция об уплате государственной пошлины на 120 000 тенге."],
    )

    errors = claim_consistency_errors("ТОО против ТОО, долг 12 000 000 тенге.", draft)

    assert not any("пошлин" in error.lower() for error in errors)


def test_representative_expense_amount_is_not_read_as_state_duty() -> None:
    """Соседняя сумма расходов на представителя — не размер пошлины."""
    draft = _duty_draft(
        state_duty="360 000 тенге (3% от цены иска; максимум 20 000 МРП; статья 665 Налогового кодекса РК)",
        attachments=[
            "Судебные расходы: государственная пошлина 360 000 тенге и услуги представителя 200 000 тенге.",
        ],
    )

    errors = claim_consistency_errors("ТОО против ТОО, долг 12 000 000 тенге.", draft)

    assert not any("пошлин" in error.lower() for error in errors)


def test_contract_base_amount_alone_does_not_define_penalty() -> None:
    context = "Прошу взыскать неустойку за нарушение срока выполнения работ."
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать неустойку, исходя из суммы договора 1 200 000 тенге."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("без конкретного размера" in error for error in errors)


def test_complete_penalty_formula_is_checkable() -> None:
    context = "Прошу взыскать неустойку за 10 дней просрочки."
    draft = _draft(
        legal_basis=["За нарушение срока выполнения работы исполнитель уплачивает неустойку."],
        requests=["Взыскать неустойку: 1% от 1 200 000 тенге за 10 дней просрочки."],
    )
    errors = claim_consistency_errors(context, draft)
    assert not any("без конкретного размера" in error for error in errors)


def test_kazakh_multiline_remedies_are_protected() -> None:
    context = (
        "Талапкер жұмыстың ақысын толық төледі, жауапкер жұмысты мерзімінде орындамады.\n"
        "Өндіріп беруді сұраймын:\n- 1 200 000 теңге;\n- тұрақсыздық айыбын;\n- сот шығындарын."
    )
    draft = _draft(
        legal_basis=["Орындаушы жұмыс мерзімін бұзғаны үшін жауап береді."],
        requests=["Жауапкерден 1 200 000 теңге өндіріп алу."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error for error in errors)


def test_kazakh_penalty_amount_in_tenge_is_accepted() -> None:
    context = "Жауапкер жұмыс мерзімін бұзды. Тұрақсыздық айыбын өндіріп беруді сұраймын."
    draft = _draft(
        legal_basis=["Жұмыс мерзімі бұзылған кезде орындаушы тұрақсыздық айыбын төлейді."],
        requests=["Тұрақсыздық айыбын 120 000 теңге өндіріп беру."],
    )
    errors = claim_consistency_errors(context, draft)
    assert not any("без конкретного размера" in error for error in errors)


def test_kazakh_buyer_nonpayment_rule_is_blocked_after_full_payment() -> None:
    context = "Талапкер 1 200 000 теңгені толық төледі. Жауапкер жұмысты орындамады."
    draft = _draft(
        legal_basis=["Сатып алушы алдын ала төлемді төлемесе, шарттан бас тартты деп есептеледі."],
        requests=["Жауапкерден 1 200 000 теңге өндіріп алу."],
    )
    errors = claim_consistency_errors(context, draft)
    assert any("другой фактической ситуации" in error for error in errors)


def test_package_install_extends_existing_senior_preflight() -> None:
    context = (
        "Я полностью оплатил работы, ответчик нарушил срок изготовления и установки кухни. "
        "Прошу взыскать 1 200 000 тенге, неустойку и судебные расходы."
    )
    draft = _draft(
        legal_basis=[
            "Неоплата покупателем предварительной оплаты считается отказом от исполнения договора.",
            "За просрочку возврата товара ненадлежащего качества выплачивается неустойка 1% стоимости товара.",
        ],
        requests=["Взыскать с Ответчика 1 200 000 тенге."],
    )
    errors = senior_claim_preflight.deterministic_claim_preflight(context, _research(), draft)
    assert getattr(senior_claim_preflight.deterministic_claim_preflight, "_korgan_claim_consistency_guard", False)
    assert any("неустойку/пеню" in error and "исчезло" in error for error in errors)
    assert any("судебные расходы" in error for error in errors)
    assert any("другой фактической ситуации" in error for error in errors)
