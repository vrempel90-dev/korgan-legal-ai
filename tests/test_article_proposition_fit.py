"""Верное утверждение под чужим номером статьи — тоже ошибка.

Проверка цитаты отвечает на вопрос «существует ли такая статья и верно ли
процитирован её текст». Она молчит о другом вопросе: говорит ли названная
статья именно то, что документ на неё ссылаясь утверждает.

Разрыв виден на сроке исковой давности. Утверждение «общий срок исковой
давности — три года» юридически верно. Если оно уходит со ссылкой на соседнюю
статью о начале течения срока, то и статья реальная, и текст нормы подлинный, и
утверждение правдивое — но норма его не содержит. Оппонент открывает ссылку и
видит другое правило; суд делает тот же вывод о качестве иска целиком.

Механическая часть проверки — величины. Норма о сроке называет срок, норма о
ставке называет ставку. Если пересказ называет «три года», «десять дней» или
«один процент», а в тексте нормы этой величины нет, ссылка почти наверняка ведёт
не туда, и статус выше NEEDS_VERIFICATION недопустим.
"""

from __future__ import annotations

from korgan.citation_audit import CitationVerdict, audit_citations
from korgan.provision_check import paraphrase_defects, verified_claim_line

# Статья 180 ГК РК — о начале течения срока. Лексика та же, что у статьи 178,
# сужающих оговорок нет, но величины «три года» в норме не содержится.
ARTICLE_180 = (
    "Течение срока исковой давности начинается со дня, когда лицо узнало или должно "
    "было узнать о нарушении права. Изъятия из этого правила устанавливаются "
    "настоящим Кодексом и иными законодательными актами."
)

ARTICLE_178 = (
    "Общий срок исковой давности устанавливается в три года. Для отдельных видов "
    "требований законодательными актами могут устанавливаться специальные сроки "
    "исковой давности, сокращенные или более длительные по сравнению с общим сроком."
)

PRETRIAL_FORM_ARTICLE = (
    "Претензия направляется в письменной форме и подписывается лицом, направляющим "
    "претензию. К претензии прилагаются документы, обосновывающие предъявленные требования."
)


# --- величина, которой нет в норме ---


def test_limitation_period_attached_to_the_wrong_article_is_a_defect() -> None:
    defects = paraphrase_defects(
        "Общий срок исковой давности устанавливается в три года.", ARTICLE_180
    )

    assert defects
    assert any("три года" in defect for defect in defects)


def test_review_deadline_attached_to_an_article_about_form_is_a_defect() -> None:
    defects = paraphrase_defects(
        "Претензия подлежит рассмотрению в течение десяти календарных дней.",
        PRETRIAL_FORM_ARTICLE,
    )

    assert defects


def test_duty_rate_attached_to_an_article_about_payers_is_a_defect() -> None:
    defects = paraphrase_defects(
        "Государственная пошлина по имущественному иску составляет один процент от суммы иска.",
        "Плательщиками государственной пошлины являются физические и юридические лица, "
        "обращающиеся за совершением юридически значимых действий.",
    )

    assert defects


# --- норма, которая эту величину действительно содержит ---


def test_limitation_period_attached_to_its_own_article_is_clean() -> None:
    assert paraphrase_defects(
        "Общий срок исковой давности устанавливается в три года.", ARTICLE_178
    ) == []


def test_digits_in_the_provision_match_words_in_the_paraphrase() -> None:
    provision = (
        "Общий срок исковой давности устанавливается в 3 (три) года и исчисляется "
        "по правилам настоящей главы."
    )

    assert paraphrase_defects("Общий срок исковой давности — три года.", provision) == []


def test_compound_wording_in_the_provision_supports_the_paraphrase() -> None:
    provision = (
        "Ответ на претензию направляется заявителю в десятидневный срок со дня её "
        "получения адресатом."
    )

    assert paraphrase_defects("Ответ на претензию даётся в течение десяти дней.", provision) == []


def test_a_provision_without_magnitudes_is_not_penalised() -> None:
    provision = (
        "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
        "обязательства и требованиями законодательства."
    )

    assert paraphrase_defects(
        "Обязательство должно исполняться надлежащим образом.", provision
    ) == []


def test_case_amounts_are_not_read_as_a_claim_about_the_norm() -> None:
    """Величины из обстоятельств дела нормой не подтверждаются и не должны."""
    provision = (
        "При просрочке исполнения обязательства должник уплачивает кредитору неустойку, "
        "предусмотренную договором."
    )
    statement = (
        "Должник обязан уплатить неустойку, предусмотренную договором. "
        "Стороны согласовали её в пункте 6.3 договора в размере 0,1 процента за каждый день просрочки."
    )

    assert paraphrase_defects(statement, provision) == []


# --- шлюз выпуска ---


def test_release_audit_blocks_a_true_sentence_under_the_wrong_article() -> None:
    verified = verified_claim_line(
        "Общий срок исковой давности устанавливается в три года",
        "статья 180 ГК РК",
        ARTICLE_180,
        "https://adilet.zan.kz/rus/docs/K940001000_",
    )
    document = (
        "ПРАВОВОЕ ОБОСНОВАНИЕ\n"
        "Общий срок исковой давности устанавливается в три года (статья 180 ГК РК).\n"
    )

    audit = audit_citations(document, verified_claims=[verified])

    assert audit.blocking
    assert audit.blocking[0].verdict is CitationVerdict.PARAPHRASE_DRIFT


def test_release_audit_passes_the_same_sentence_under_its_own_article() -> None:
    verified = verified_claim_line(
        "Общий срок исковой давности устанавливается в три года",
        "статья 178 ГК РК",
        ARTICLE_178,
        "https://adilet.zan.kz/rus/docs/K940001000_",
    )
    document = (
        "ПРАВОВОЕ ОБОСНОВАНИЕ\n"
        "Общий срок исковой давности устанавливается в три года (статья 178 ГК РК).\n"
    )

    audit = audit_citations(document, verified_claims=[verified])

    assert audit.blocking == []
