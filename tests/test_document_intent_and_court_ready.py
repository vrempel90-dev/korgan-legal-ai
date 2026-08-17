from __future__ import annotations

from korgan.court_ready_claim_guard import add_gpk_filing_actions, substantive_release_defects
from korgan.document_intent_guard import detect_document_intent, selected_intent_mismatch
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import sanitize_prayer_requests


def _research(*verified: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(verified),
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000414"] if verified else [],
        notes=[],
    )


def _draft(*, requests: list[str], legal_basis: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по заработной плате",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]",
        claimant=[
            "Жумабекова Айгерим Толегеновна",
            "Адрес: г. Шымкент, ул. Кунаева, 9-41",
            "ИИН: 910422401278",
            "Дата рождения: [ТРЕБУЕТ УТОЧНЕНИЯ: дата рождения истца]",
        ],
        defendant=[
            "ТОО «Алтын Сауда»",
            "БИН: 070915300871",
            "Адрес: г. Шымкент, ул. Байтурсынова, 22",
        ],
        price_of_claim="420 000 тенге",
        state_duty="[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]",
        facts=[
            "Истец работала у ответчика по трудовому договору.",
            "30.06.2026 трудовой договор прекращен.",
            "Заработная плата за июнь 2026 года 420 000 тенге не выплачена.",
        ],
        legal_basis=list(legal_basis),
        requests=list(requests),
        attachments=["Копия трудового договора"],
        verification_notes=[],
        source_urls=[],
    )


def test_detects_each_requested_document_type_in_russian() -> None:
    assert detect_document_intent("подготовь иск о взыскании долга по договору займа") == "claim"
    assert detect_document_intent("составь досудебную претензию перед обращением в суд") == "pretrial"
    assert detect_document_intent("подготовь отзыв на иск истца") == "response"
    assert detect_document_intent("составь договор аренды помещения") == "contract"


def test_detects_each_requested_document_type_in_kazakh() -> None:
    assert detect_document_intent("талап қою арызын дайында") == "claim"
    assert detect_document_intent("сотқа дейінгі талапты дайында") == "pretrial"
    assert detect_document_intent("талап қою арызына пікір дайында") == "response"
    assert detect_document_intent("қызмет көрсету шартын дайында") == "contract"


def test_advice_question_is_not_misrouted_as_document() -> None:
    assert detect_document_intent("как составить договор аренды?") is None
    assert detect_document_intent("талап қою арызын қалай дайындауға болады?") is None
    assert detect_document_intent("шартты қалай дайындауға болады?") is None


def test_selected_claim_rejects_explicit_contract_request() -> None:
    mismatch = selected_intent_mismatch("universal_claim_waiting", "составь договор оказания услуг")
    assert mismatch is not None
    assert mismatch.selected == "claim"
    assert mismatch.requested == "contract"


def test_selected_contract_rejects_explicit_claim_request() -> None:
    mismatch = selected_intent_mismatch("contract_details", "подготовь иск о взыскании долга")
    assert mismatch is not None
    assert mismatch.selected == "contract"
    assert mismatch.requested == "claim"


def test_same_selected_document_or_plain_facts_are_not_blocked() -> None:
    assert selected_intent_mismatch("pretrial_waiting", "подготовь досудебную претензию") is None
    assert selected_intent_mismatch("universal_claim_waiting", "Ответчик не вернул 800 000 тенге") is None


def test_prayer_drops_model_reasoning_after_executable_request() -> None:
    draft = _draft(
        legal_basis=["Работодатель обязан выплатить заработную плату. Правовое основание: статья 113 ТК РК."],
        requests=[
            "Взыскать с ответчика 420 000 тенге задолженности. "
            "Фактические основания: зарплата не выплачена. "
            "Правовое основание: пункт 3 Республики Казахстан. "
            "Юридическое последствие: сумма подлежит взысканию."
        ],
    )
    sanitize_prayer_requests(draft)
    assert draft.requests == ["Взыскать с ответчика 420 000 тенге задолженности."]


def test_prayer_removes_broken_republic_of_kazakhstan_prefix() -> None:
    draft = _draft(
        legal_basis=["Правовое основание: статья 243 ГПК РК."],
        requests=["На основании Республики Казахстан обратить решение суда к немедленному исполнению."],
    )
    sanitize_prayer_requests(draft)
    assert draft.requests == ["Обратить решение суда к немедленному исполнению."]


def test_prayer_preserves_real_article_prefix() -> None:
    draft = _draft(
        legal_basis=["Правовое основание: статья 243 ГПК РК."],
        requests=["На основании статьи 243 ГПК РК обратить решение суда к немедленному исполнению."],
    )
    sanitize_prayer_requests(draft)
    assert draft.requests == ["На основании статьи 243 ГПК РК обратить решение суда к немедленному исполнению."]


def test_internal_verification_text_is_a_substantive_release_blocker() -> None:
    verified = (
        "Работодатель обязан своевременно выплатить заработную плату. "
        "[основание: статья 113 ТК РК; текст нормы: «заработная плата выплачивается»; "
        "источник: https://adilet.zan.kz/rus/docs/K1500000414]"
    )
    draft = _draft(
        legal_basis=[
            "[ТРЕБУЕТ ПРОВЕРКИ: статья 113 ТК РК подлежит сверке по официальному источнику]"
        ],
        requests=["Взыскать задолженность по заработной плате 420 000 тенге."],
    )
    defects = substantive_release_defects("Работодатель не выплатил зарплату 420 000 тенге.", _research(verified), draft)
    assert defects
    assert any("правов" in item.lower() or "verification" in item.lower() for item in defects)


def test_salary_request_without_verified_salary_basis_is_blocked() -> None:
    draft = _draft(
        legal_basis=["Общие положения трудового законодательства."],
        requests=["Взыскать задолженность по заработной плате 420 000 тенге."],
    )
    defects = substantive_release_defects("Работодатель не выплатил зарплату 420 000 тенге.", _research(), draft)
    assert any("verified" in item.lower() for item in defects)


def test_formal_gpk_fields_become_filing_actions_not_questionnaire_rounds() -> None:
    draft = _draft(
        legal_basis=["Работодатель обязан выплатить заработную плату. Правовое основание: статья 113 ТК РК."],
        requests=["Взыскать задолженность по заработной плате 420 000 тенге."],
    )
    actions = add_gpk_filing_actions("Работодатель не выплатил зарплату.", _research(), draft)
    joined = "\n".join(actions).lower()
    assert "суд" in joined
    assert "дата рождения" in joined
    assert "госпошлин" in joined
