from __future__ import annotations

import io

from docx import Document

from korgan.contract_docx import build_contract_docx
from korgan.fast_v2_production_legal import (
    _is_state_duty_request,
    _mark_uncertain_dates,
    _normalize_state_duty_request,
    _remove_false_state_duty_evidence,
)
from korgan.legal_routing import detect_claim_profile, detect_contract_profile
from korgan.legal_types import ClaimDraft, ContractDraft, ContractSection, VerificationStatus


def _claim() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="150 000 тенге",
        facts=["Перевод был примерно 12.06.2026."],
        legal_basis=[],
        requests=["Взыскать 150 000 тенге.", "Взыскать госпошлину 6 500 тенге."],
        attachments=["Банковские документы", "[ТРЕБУЕТ ДОБАВИТЬ: квитанция госпошлины]"],
        verification_notes=[],
        source_urls=[],
        state_duty="1 500 тенге (1% от цены иска)",
    )


def test_routes_loan_claim_without_extra_model_call() -> None:
    profile = detect_claim_profile("Я дал ответчику деньги в долг, он обещал вернуть через два месяца")
    assert profile.code == "loan_debt"
    assert "715" in profile.research_focus
    assert "716" in profile.research_focus
    assert "722" in profile.research_focus


def test_contract_router_distinguishes_services_and_loan() -> None:
    assert detect_contract_profile("Нужен договор оказания услуг между заказчиком и исполнителем").code == "services"
    assert detect_contract_profile("Составить договор займа на 500 000 тенге").code == "loan"


def test_uncertain_date_is_marked_only_once() -> None:
    draft = _claim()
    _mark_uncertain_dates("Точную дату надо сверить по банку, примерно 12.06.2026", draft)
    text = " ".join(draft.facts).lower()
    assert text.count("ориентировочно") == 1
    assert text.count("точная дата требует сверки") == 1


def test_state_duty_request_is_replaced_by_deterministic_amount() -> None:
    draft = _claim()
    _normalize_state_duty_request(draft)
    duty_requests = [x for x in draft.requests if _is_state_duty_request(x)]
    assert duty_requests == ["Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере 1 500 тенге."]
    assert "6 500" not in " ".join(draft.requests)


def test_missing_state_duty_receipt_stays_out_of_annexes() -> None:
    draft = _claim()
    _remove_false_state_duty_evidence("ИИН истца 900000000001. Цена иска 150 000 тенге.", draft)
    assert not any("пошлин" in item.lower() for item in draft.attachments)


def test_contract_docx_contains_sections_and_no_source_urls() -> None:
    draft = ContractDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        contract_type="договор оказания услуг",
        title="ДОГОВОР ОКАЗАНИЯ УСЛУГ",
        place_and_date="г. Алматы, 16.08.2026",
        party_a=["ТОО «Заказчик»"],
        party_b=["ИП Исполнитель"],
        preamble=["ТОО «Заказчик» и ИП Исполнитель заключили настоящий договор."],
        sections=[
            ContractSection("Предмет договора", ["Исполнитель оказывает согласованные услуги."]),
            ContractSection("Порядок оплаты", ["Цена и порядок оплаты определяются сторонами в приложении."]),
        ],
        requisites_a=["ТОО «Заказчик»"],
        requisites_b=["ИП Исполнитель"],
        verification_notes=["Нужно уточнить перечень услуг."],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )
    data = build_contract_docx(draft)
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ДОГОВОР ОКАЗАНИЯ УСЛУГ" in text
    assert "1. Предмет договора" in text
    assert "2. Порядок оплаты" in text
    assert "https://" not in text
