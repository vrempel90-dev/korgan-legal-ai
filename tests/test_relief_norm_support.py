"""Санкцию нельзя вывести из нормы о надлежащем исполнении.

Статья 272 ГК РК говорит, что обязательство должно исполняться надлежащим
образом. Из неё следует обязанность исполнить — и ничего больше. Неустойка,
убытки и моральный вред живут по собственным правилам: неустойка существует
только там, где её предусмотрели закон или письменный договор; моральный вред —
только там, где его допускает закон.

Разрыв, который здесь закрывается, выглядел так: иск требовал 450 000 тенге
неустойки, всё правовое обоснование состояло из подтверждённой статьи 272 ГК РК,
и документ выпускался с оценкой 10.0 и статусом «готов». Ссылка настоящая, текст
нормы подлинный, пересказ точный — а основания требования нет вовсе.

Подтверждением требования считается только то, что модель не может выписать
себе сама: текст нормы, привязанный к официальному источнику, либо условие
договора, названное в материалах дела. Собственная формулировка документа
«ответчик обязан уплатить неустойку» основанием не является — это и есть
проверяемое утверждение.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft
from korgan.provision_check import verified_claim_line
from korgan.relief_norm_support import unsupported_relief

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"

ARTICLE_272 = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства, а при отсутствии таких условий и "
    "требований — в соответствии с обычаями делового оборота."
)
ARTICLE_293 = (
    "Неустойкой (штрафом, пеней) признается определенная законодательством или договором "
    "денежная сумма, которую должник обязан уплатить кредитору в случае неисполнения или "
    "ненадлежащего исполнения обязательства, в частности в случае просрочки исполнения."
)
ARTICLE_9_DAMAGES = (
    "Под убытками понимаются расходы, которые произведены или должны быть произведены "
    "лицом, право которого нарушено, утрата или повреждение его имущества, а также "
    "неполученные доходы, которые это лицо получило бы при обычных условиях оборота."
)

GENERAL_ONLY = [verified_claim_line("Обязательство должно исполняться надлежащим образом", "статья 272 ГК РК", ARTICLE_272, ADILET)]
PENALTY_NORM = [*GENERAL_ONLY, verified_claim_line("Неустойка определяется законодательством или договором", "статья 293 ГК РК", ARTICLE_293, ADILET)]

CONTEXT = (
    "Истец: ТОО «АЛЬЯНС», БИН 180340012345, г. Астана.\n"
    "Ответчик: ТОО «СТРОЙ ГРУПП», БИН 200140012345.\n"
    "12.01.2026 заключён договор поставки, оборудование поставлено с просрочкой на 30 дней."
)

PENALTY_REQUEST = ["Взыскать с ответчика неустойку в размере 450 000 тенге."]
MODEL_CONCLUSION = [
    "Обязательство должно исполняться надлежащим образом. "
    "Ответчик нарушил согласованный срок, в связи с чем обязан уплатить неустойку "
    "в размере 450 000 тенге. Правовое основание: статья 272 ГК РК."
]
FACTS = [
    "12.01.2026 между сторонами заключён договор поставки оборудования.",
    "Срок поставки согласован сторонами — 01.02.2026.",
    "Оборудование фактически поставлено 03.03.2026, с просрочкой в 30 дней.",
]


# --- неустойка ---


def test_penalty_on_a_general_performance_norm_is_unsupported() -> None:
    findings = unsupported_relief(
        requests=PENALTY_REQUEST,
        legal_basis=MODEL_CONCLUSION,
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=GENERAL_ONLY,
    )

    assert findings
    assert any("неустойк" in finding.lower() for finding in findings)


def test_penalty_backed_by_its_own_norm_is_supported() -> None:
    assert unsupported_relief(
        requests=PENALTY_REQUEST,
        legal_basis=MODEL_CONCLUSION,
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=PENALTY_NORM,
    ) == []


def test_penalty_backed_by_a_contract_clause_is_supported() -> None:
    facts = [*FACTS, "Пунктом 6.3 договора предусмотрена неустойка 0,1 % за каждый день просрочки."]

    assert unsupported_relief(
        requests=PENALTY_REQUEST,
        legal_basis=MODEL_CONCLUSION,
        case_context=CONTEXT,
        facts=facts,
        verified_claims=GENERAL_ONLY,
    ) == []


def test_the_documents_own_wording_is_not_authority_for_itself() -> None:
    """«Ответчик обязан уплатить неустойку» — это вывод, а не его основание."""
    basis = ["Неустойка подлежит взысканию с ответчика на основании статьи 272 ГК РК."]

    assert unsupported_relief(
        requests=PENALTY_REQUEST,
        legal_basis=basis,
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=GENERAL_ONLY,
    )


# --- убытки и моральный вред ---


def test_damages_without_a_norm_about_damages_are_unsupported() -> None:
    findings = unsupported_relief(
        requests=["Взыскать с ответчика убытки в размере 800 000 тенге."],
        legal_basis=["Ответчик обязан возместить причинённые убытки."],
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=GENERAL_ONLY,
    )

    assert findings


def test_damages_backed_by_the_damages_norm_are_supported() -> None:
    assert unsupported_relief(
        requests=["Взыскать с ответчика убытки в размере 800 000 тенге."],
        legal_basis=["Ответчик обязан возместить причинённые убытки."],
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=[
            *GENERAL_ONLY,
            verified_claim_line("Под убытками понимаются расходы", "статья 9 ГК РК", ARTICLE_9_DAMAGES, ADILET),
        ],
    ) == []


def test_a_contract_clause_cannot_create_moral_damage() -> None:
    findings = unsupported_relief(
        requests=["Взыскать компенсацию морального вреда в размере 300 000 тенге."],
        legal_basis=["Ответчик обязан компенсировать моральный вред."],
        case_context=CONTEXT,
        facts=[*FACTS, "Пунктом 8.1 договора предусмотрена компенсация морального вреда."],
        verified_claims=GENERAL_ONLY,
    )

    assert findings


# --- требования, у которых собственной нормы не требуется ---


def test_plain_debt_recovery_is_not_touched() -> None:
    assert unsupported_relief(
        requests=["Взыскать с ответчика основной долг в размере 1 200 000 тенге."],
        legal_basis=["Обязательство должно исполняться надлежащим образом."],
        case_context=CONTEXT,
        facts=FACTS,
        verified_claims=GENERAL_ONLY,
    ) == []


# --- шлюз выпуска ---


def _claim(*, legal_basis: list[str], requests: list[str]) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление о взыскании неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО «АЛЬЯНС», БИН 180340012345"],
        defendant=["ТОО «СТРОЙ ГРУПП», БИН 200140012345"],
        price_of_claim="450 000 тенге",
        state_duty="13 500 тенге",
        facts=list(FACTS),
        legal_basis=legal_basis,
        requests=requests,
        attachments=["Договор поставки от 12.01.2026", "Накладная от 03.03.2026"],
        verification_notes=[],
        source_urls=[ADILET],
    )


def _research(verified: list[str]) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["статья 272 ГК РК"],
        procedural_requirements=[],
        verified_claims=verified,
        unverified_claims=[],
        notes=["VERIFIED_COURT: Специализированный межрайонный экономический суд города Астаны"],
        source_urls=[ADILET],
    )


def test_quality_gate_blocks_a_penalty_claim_without_a_penalty_norm() -> None:
    draft = _claim(legal_basis=MODEL_CONCLUSION, requests=PENALTY_REQUEST)

    report = assess_document_quality("claim", CONTEXT, _research(GENERAL_ONLY), draft)

    assert report.ready is False
    assert any("неустойк" in blocker.lower() for blocker in report.hard_blockers)


def test_quality_gate_releases_the_same_claim_once_the_norm_is_verified() -> None:
    draft = _claim(legal_basis=MODEL_CONCLUSION, requests=PENALTY_REQUEST)

    report = assess_document_quality("claim", CONTEXT, _research(PENALTY_NORM), draft)

    assert not any("неустойк" in blocker.lower() for blocker in report.hard_blockers)


def _pretrial(*, facts: list[str]) -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["ТОО «АЛЬЯНС», БИН 180340012345", "г. Астана"],
        recipient=["ТОО «СТРОЙ ГРУПП», БИН 200140012345", "г. Астана"],
        facts=facts,
        legal_basis=["Обязательство должно исполняться надлежащим образом (статья 272 ГК РК)."],
        demands=["Просим уплатить неустойку за просрочку поставки в размере 450 000 тенге."],
        deadline="10 календарных дней",
        consequences=["В случае неисполнения требование будет заявлено в суд."],
        attachments=["Копия договора поставки от 12.01.2026"],
        calculation=["Неустойка: 450 000 тенге."],
    )


def test_pretrial_demand_for_a_penalty_needs_the_same_basis() -> None:
    """Претензия закрыта тем же инвариантом — своим владельцем.

    Требование неустойки в претензии проходит remedy_support_issues, и там
    правило строже: собственная VERIFIED-норма обязательна, договорной
    альтернативы нет. Второй такой же проверки в _score_pretrial не ставится,
    но инвариант должен держаться, поэтому он зафиксирован здесь.
    """
    report = assess_document_quality(
        "pretrial", CONTEXT, _research(GENERAL_ONLY), _pretrial(facts=list(FACTS))
    )

    assert report.ready is False
    assert any("неустойк" in blocker.lower() for blocker in report.hard_blockers)


def test_pretrial_demand_is_released_once_the_penalty_norm_is_verified() -> None:
    draft = _pretrial(facts=list(FACTS))
    draft.legal_basis.append("Неустойка определяется законодательством или договором (статья 293 ГК РК).")

    report = assess_document_quality("pretrial", CONTEXT, _research(PENALTY_NORM), draft)

    assert not any("неустойк" in blocker.lower() for blocker in report.hard_blockers)
