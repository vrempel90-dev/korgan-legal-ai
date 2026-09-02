"""Регрессия фазы 2: номер статьи печатается только при verified lookup.

Два кейса взяты из боевых обращений.

Кейс 1 — срок исковой давности. Генератор пишет «ст. 178, 180 ГК РК». Прежний
разбор ссылок находил в этой строке только 178: перечисление он не понимал, и
непроверенная 180 проходила в документ, потому что её никто не искал. Корпус
подтверждает 178 и 183; 180 в подтверждённых источниках нет.

Кейс 2 — обязанность покупателя оплатить товар. Генератор ссылается на ст. 458
ГК РК. Статья существует и подтверждена корпусом, но она отсылочная: к поставке
применяются правила о купле-продаже. Обязанность оплаты создаёт ст. 439, к
которой отсылка ведёт, а не сама отсылка.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
from docx import Document

from korgan.article_authority import (
    AUTHORITY_NOTE_PREFIX,
    enforce_article_authority,
    find_citations,
)
from korgan.article_lookup import LookupResult, lookup_article, source_hash
from korgan.claim_docx import build_claim_docx
from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_GENERAL, ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import apply_article_authority

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"

CHECKED_ON = date.today().isoformat()

ARTICLE_178 = "Общий срок исковой давности устанавливается в три года."
ARTICLE_183 = (
    "Течение срока исковой давности прерывается предъявлением иска в установленном порядке, "
    "а также совершением обязанным лицом действий, свидетельствующих о признании долга."
)
# Отсылочная норма: правило она не устанавливает, а отправляет к правилам о
# купле-продаже. Ровно поэтому она не может быть основанием требования об оплате.
ARTICLE_458 = (
    "К отношениям по договору поставки применяются правила о договоре купли-продажи, "
    "если иное не предусмотрено правилами настоящего параграфа."
)
ARTICLE_439 = (
    "Покупатель обязан оплатить товар непосредственно до или после передачи ему продавцом товара, "
    "если иное не предусмотрено законодательными актами или договором купли-продажи."
)
ARTICLE_GPK_27 = (
    "Специализированные межрайонные экономические суды рассматривают имущественные и неимущественные споры, "
    "сторонами которых являются юридические лица, индивидуальные предприниматели."
)


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Корпус, в котором подтверждены 178, 183, 458, 439 и ГПК 27 — но не 180."""
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(ACT_GK_GENERAL, "K940001000_", "ГК РК (Общая часть)", GK_GENERAL_URL, CHECKED_ON, CHECKED_ON)
        db.upsert_act(ACT_GK_SPECIAL, "K990000409_", "ГК РК (Особенная часть)", GK_SPECIAL_URL, CHECKED_ON, CHECKED_ON)
        db.upsert_act(ACT_GPK, "K1500000377", "ГПК РК", GPK_URL, CHECKED_ON, CHECKED_ON)
        for act, article, heading, body, url in (
            (ACT_GK_GENERAL, "178", "Общие сроки исковой давности", ARTICLE_178, GK_GENERAL_URL),
            (ACT_GK_GENERAL, "183", "Перерыв течения срока исковой давности", ARTICLE_183, GK_GENERAL_URL),
            (ACT_GK_SPECIAL, "458", "Договор поставки", ARTICLE_458, GK_SPECIAL_URL),
            (ACT_GK_SPECIAL, "439", "Оплата товара", ARTICLE_439, GK_SPECIAL_URL),
            (ACT_GPK, "27", "Подсудность дел экономическим судам", ARTICLE_GPK_27, GPK_URL),
        ):
            db.upsert_provision(
                act_id=act,
                article_no=article,
                item_no=None,
                heading=heading,
                body=body,
                edition_date=CHECKED_ON,
                url=url,
                sort_key=int(article),
            )

    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _draft(**overrides) -> ClaimDraft:
    base = dict(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по договору поставки",
        court="Специализированный межрайонный экономический суд города Алматы",
        claimant=["ТОО «Альфа», БИН 190440012345"],
        defendant=["ТОО «Бета», БИН 200540067890"],
        price_of_claim="1 800 000 тенге",
        facts=["Товар поставлен, оплата не произведена."],
        legal_basis=[],
        requests=["Взыскать с ответчика основной долг."],
        attachments=["Копия договора поставки"],
        verification_notes=[],
        source_urls=[],
    )
    base.update(overrides)
    return ClaimDraft(**base)


def _docx_text(draft: ClaimDraft) -> str:
    document = Document(io.BytesIO(build_claim_docx(draft)))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


# --------------------------------------------------------------------------
# Контракт lookup
# --------------------------------------------------------------------------


def test_lookup_returns_a_structured_result(corpus) -> None:
    result = lookup_article("ГК РК", "178")

    assert result.found is True
    assert result.verified is True
    assert result.code == "ГК РК"
    assert result.article == "178"
    # Заголовок статьи — часть нормы: без него текст статьи 27 ГПК РК не
    # содержит слова «подсудность», и верный пересказ объявлялся дрейфом.
    assert result.source_hash == source_hash(f"Общие сроки исковой давности. {ARTICLE_178}")
    assert result.source_url == GK_GENERAL_URL


def test_missing_article_is_found_false_with_a_reason(corpus) -> None:
    result = lookup_article("ГК РК", "180")

    assert result.found is False
    assert result.verified is False
    assert result.source_hash == ""
    assert "180" in result.reason


def test_source_hash_follows_the_text_not_the_number(corpus) -> None:
    """Номер статьи переживает смену редакции, отпечаток — нет."""
    assert source_hash(ARTICLE_178) != source_hash(ARTICLE_178 + " Изменённая редакция.")
    assert source_hash(ARTICLE_178) == source_hash("  Общий  срок исковой давности устанавливается в три года. ")


def test_an_unknown_act_is_never_verified() -> None:
    result = lookup_article("Кодекс Атлантиды", "1")

    assert result.found is False
    assert result.verified is False


# --------------------------------------------------------------------------
# Разбор ссылок: перечисления
# --------------------------------------------------------------------------


def test_enumerated_articles_are_all_visible_to_the_check() -> None:
    """Прежний разбор находил в перечислении только первый номер."""
    sites = find_citations("В соответствии со ст. 178, 180 ГК РК срок исковой давности составляет три года.")

    assert len(sites) == 1
    assert sites[0].code == "ГК РК"
    assert sites[0].articles == ("178", "180")


def test_long_enumeration_with_conjunction_is_parsed() -> None:
    sites = find_citations("Согласно статьям 178, 180 и 183 ГК РК срок прерывается.")

    assert sites[0].articles == ("178", "180", "183")


# --------------------------------------------------------------------------
# Кейс 1: ст. 178, 180 ГК РК
# --------------------------------------------------------------------------


def test_case_one_keeps_the_verified_article_and_drops_the_unverified(corpus) -> None:
    draft = _draft(
        legal_basis=[
            "В соответствии со ст. 178, 180 ГК РК общий срок исковой давности устанавливается в три года.",
        ]
    )

    report = enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "178" in printed
    assert "180" not in printed, "непроверенная статья 180 осталась в документе"
    assert {item.article for item in report.printed} == {"178"}
    assert {item.article for item in report.suppressed} == {"180"}


def test_case_one_verified_combination_is_178_and_183(corpus) -> None:
    """Корпус подтверждает 178 и 183 — обе печатаются, 180 снимается."""
    draft = _draft(
        legal_basis=[
            "Согласно статьям 178, 180 и 183 ГК РК течение срока исковой давности прерывается "
            "предъявлением иска в установленном порядке.",
        ]
    )

    enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "178" in printed and "183" in printed
    assert "180" not in printed


def test_case_one_without_any_verified_article_prints_no_number(corpus) -> None:
    """Ни одна статья не подтверждена — остаётся общая формулировка без номера."""
    draft = _draft(
        legal_basis=[
            "В соответствии со ст. 180 ГК РК срок исковой давности прерывается признанием долга.",
        ]
    )

    enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "180" not in printed
    assert "ст." not in printed and "стать" not in printed
    assert "гражданского законодательства Республики Казахстан" in printed
    # Смысл предложения сохранён: снят номер, а не позиция.
    assert "срок исковой давности прерывается" in printed


def test_generic_wording_agrees_with_its_preposition(corpus) -> None:
    """«со ст. 180» после замены не превращается в «со нормами»."""
    draft = _draft(
        legal_basis=["В соответствии со ст. 180 ГК РК срок исковой давности прерывается."]
    )

    enforce_article_authority(draft)

    assert draft.legal_basis[0].startswith("В соответствии с нормами гражданского законодательства")


def test_case_one_reports_the_suppressed_article_to_the_lawyer(corpus) -> None:
    draft = _draft(
        legal_basis=["В соответствии со ст. 178, 180 ГК РК срок исковой давности составляет три года."]
    )

    report = enforce_article_authority(draft)

    assert any("180" in note for note in report.lawyer_notes)
    assert all(note.startswith(AUTHORITY_NOTE_PREFIX) for note in report.lawyer_notes)


# --------------------------------------------------------------------------
# Кейс 2: ст. 458 ГК РК как основание обязанности оплатить
# --------------------------------------------------------------------------


def test_case_two_referral_article_is_not_a_ground_for_payment(corpus) -> None:
    """458 подтверждена корпусом, но она отсылочная и правила не устанавливает."""
    draft = _draft(
        legal_basis=[
            "Согласно ст. 458 ГК РК покупатель обязан оплатить поставленный товар в срок, "
            "установленный договором поставки.",
        ]
    )

    report = enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "458" not in printed
    suppressed = {item.article: item for item in report.suppressed}
    assert "458" in suppressed
    assert suppressed["458"].lookup.found is True
    assert suppressed["458"].lookup.verified is True
    assert "отсылочной" in suppressed["458"].detail


def test_case_two_the_correct_norm_is_printed(corpus) -> None:
    """Обязанность оплаты опирается на 439 — норму, текст которой её создаёт."""
    draft = _draft(
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
        ]
    )

    report = enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "439" in printed
    assert {item.article for item in report.printed} == {"439"}


def test_case_two_chain_keeps_439_and_drops_458(corpus) -> None:
    """В цепочке «458 → 439» печатается та норма, которая создаёт обязанность."""
    draft = _draft(
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
            "Согласно ст. 458 ГК РК покупатель обязан оплатить поставленный товар.",
        ]
    )

    enforce_article_authority(draft)

    printed = "\n".join(draft.legal_basis)
    assert "439" in printed
    assert "458" not in printed


def test_referral_article_survives_when_the_statement_matches_it(corpus) -> None:
    """458 остаётся, когда документ говорит о ней то, что в ней написано."""
    draft = _draft(
        legal_basis=[
            "В соответствии со ст. 458 ГК РК к отношениям по договору поставки применяются "
            "правила о договоре купли-продажи, если иное не предусмотрено правилами настоящего параграфа.",
        ]
    )

    report = enforce_article_authority(draft)

    assert "458" in "\n".join(draft.legal_basis)
    assert {item.article for item in report.printed} == {"458"}


# --------------------------------------------------------------------------
# Охват: номер статьи проверяется в каждом разделе
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    ["facts", "requests", "attachments", "motions", "anticipated_defenses"],
)
def test_unverified_article_is_removed_from_every_list_section(corpus, field_name) -> None:
    """Прежняя проверка смотрела только раздел правового обоснования."""
    draft = _draft()
    setattr(
        draft,
        field_name,
        ["В соответствии со ст. 180 ГК РК срок исковой давности прерывается признанием долга."],
    )

    enforce_article_authority(draft)

    assert "180" not in "\n".join(getattr(draft, field_name))


def test_unverified_article_is_removed_from_jurisdiction_reason(corpus) -> None:
    draft = _draft(
        jurisdiction_reason="В соответствии со ст. 999 ГПК РК дело подсудно этому суду."
    )

    enforce_article_authority(draft)

    assert "999" not in draft.jurisdiction_reason


def test_verified_procedural_article_stays_in_jurisdiction_reason(corpus) -> None:
    draft = _draft(
        jurisdiction_reason=(
            "В соответствии со статьёй 27 ГПК РК спор между юридическими лицами рассматривают "
            "специализированные межрайонные экономические суды."
        )
    )

    enforce_article_authority(draft)

    assert "27" in draft.jurisdiction_reason


def test_line_without_a_preposition_is_removed_whole(corpus) -> None:
    """Без предложной конструкции замена сломала бы согласование."""
    draft = _draft(legal_basis=["Ст. 180 ГК РК устанавливает перерыв срока исковой давности."])

    report = enforce_article_authority(draft)

    assert draft.legal_basis == []
    assert report.removed_lines


# --------------------------------------------------------------------------
# Traceability
# --------------------------------------------------------------------------


def test_every_printed_article_is_linked_to_a_source_hash(corpus) -> None:
    draft = _draft(
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
        ],
        jurisdiction_reason=(
            "В соответствии со статьёй 27 ГПК РК спор между юридическими лицами рассматривают "
            "специализированные межрайонные экономические суды."
        ),
    )

    report = enforce_article_authority(draft)
    trace = report.traceability()

    assert {row["article"] for row in trace} == {"439", "27"}
    for row in trace:
        assert row["source_hash"]
        assert row["source_url"].startswith("https://adilet.zan.kz/")


def test_traceability_is_attached_to_the_draft(corpus) -> None:
    draft = _draft(
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
        ]
    )

    apply_article_authority(draft)

    trace = draft.citation_authority["traceability"]
    assert [row["article"] for row in trace] == ["439"]
    assert trace[0]["source_hash"] == source_hash(f"Оплата товара. {ARTICLE_439}")


def test_printed_article_count_matches_traceability_rows(corpus) -> None:
    """Каждое напечатанное упоминание имеет запись, и наоборот."""
    draft = _draft(
        legal_basis=[
            "В соответствии со ст. 178, 180 ГК РК общий срок исковой давности устанавливается в три года.",
        ]
    )

    report = enforce_article_authority(draft)

    printed_numbers = {
        article
        for site in find_citations("\n".join(draft.legal_basis))
        for article in site.articles
    }
    assert printed_numbers == {row["article"] for row in report.traceability()}


# --------------------------------------------------------------------------
# Готовый документ
# --------------------------------------------------------------------------


def test_no_unverified_article_number_reaches_the_docx(corpus) -> None:
    draft = _draft(
        facts=["Ответчик признал долг, что по ст. 180 ГК РК прерывает срок исковой давности."],
        legal_basis=[
            "В соответствии со ст. 178, 180 ГК РК общий срок исковой давности составляет три года.",
            "Согласно ст. 458 ГК РК покупатель обязан оплатить поставленный товар.",
        ],
    )

    apply_article_authority(draft)
    rendered = _docx_text(draft)

    for suppressed in ("180", "458"):
        assert f"ст. {suppressed}" not in rendered
        assert f"статьи {suppressed}" not in rendered
        assert f"статье {suppressed}" not in rendered
    assert "178" in rendered


def test_lawyer_message_never_reaches_the_court_text(corpus) -> None:
    draft = _draft(
        legal_basis=["В соответствии со ст. 180 ГК РК срок исковой давности прерывается."]
    )

    apply_article_authority(draft)
    rendered = _docx_text(draft)

    assert AUTHORITY_NOTE_PREFIX not in rendered
    assert any(note.startswith(AUTHORITY_NOTE_PREFIX) for note in draft.verification_notes)


def test_suppressed_article_marks_the_draft_for_review(corpus) -> None:
    draft = _draft(
        legal_basis=["В соответствии со ст. 180 ГК РК срок исковой давности прерывается."]
    )

    apply_article_authority(draft)

    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_a_fully_verified_draft_is_left_untouched(corpus) -> None:
    draft = _draft(
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
        ]
    )
    before = list(draft.legal_basis)

    apply_article_authority(draft)

    assert draft.legal_basis == before
    assert draft.status is VerificationStatus.VERIFIED
    assert not [n for n in draft.verification_notes if n.startswith(AUTHORITY_NOTE_PREFIX)]


# --------------------------------------------------------------------------
# Модель не может протащить номер мимо lookup
# --------------------------------------------------------------------------


def test_model_invented_article_number_is_suppressed(corpus) -> None:
    """Правдоподобное число, которого нет в корпусе, выглядит как настоящее."""
    draft = _draft(
        legal_basis=["В соответствии со ст. 1247 ГК РК ответчик обязан возместить убытки."]
    )

    report = enforce_article_authority(draft)

    assert "1247" not in "\n".join(draft.legal_basis)
    assert {item.article for item in report.suppressed} == {"1247"}


def test_reported_only_record_does_not_license_the_number(corpus, monkeypatch) -> None:
    """Запись со слов оператора — это found без verified."""
    from korgan import article_lookup

    def reported_lookup(code: str, article: str, part: str = "") -> LookupResult:
        from korgan.provision_corpus import REPORTED, ProvisionRecord

        return article_lookup.from_record(
            code,
            article,
            part,
            ProvisionRecord(
                act=code,
                act_aliases=(),
                article=article,
                part=part,
                text="Некоторый текст нормы, записанный со слов оператора службы поддержки.",
                source_url="",
                verified_on="",
                level=REPORTED,
                provenance="запись оператора",
            ),
            origin="реестр провизий KORGAN",
        )

    draft = _draft(
        legal_basis=["В соответствии со ст. 180 ГК РК срок исковой давности прерывается."]
    )

    report = enforce_article_authority(draft, lookup=reported_lookup)

    assert "180" not in "\n".join(draft.legal_basis)
    suppressed = report.suppressed[0]
    assert suppressed.lookup.found is True
    assert suppressed.lookup.verified is False


def test_article_number_inside_a_service_marker_is_not_a_citation(corpus) -> None:
    """Пометка о том, что норма НЕ подтверждена, — не ссылка на норму.

    Предыдущий слой пишет «[ТРЕБУЕТ ПРОВЕРКИ: ... статья 353 ГК РК не
    подтверждена ...]». Прочитать этот номер как утверждение о праве значит
    снять требование за то, что система честно сообщила о пробеле.
    """
    line = (
        "Взыскать заявленную клиентом неустойку в размере 996 000 тенге. "
        "[ТРЕБУЕТ ПРОВЕРКИ: договорную ставку нельзя извлечь из материалов, "
        "а статья 353 ГК РК не подтверждена source-bound исследованием.]"
    )
    draft = _draft(requests=[line])

    report = enforce_article_authority(draft)

    assert draft.requests == [line]
    assert report.decisions == []


def test_state_duty_article_is_verified_by_the_rate_registry() -> None:
    """Статья 665 НК РК приходит из справочника ставок, а не из текста иска.

    Строку госпошлины пишет детерминированный расчёт, и ставку он берёт из
    ``data/rates.json`` — записи с датой сверки и официальной страницей Adilet.
    Это подтверждённый источник того же класса, что и корпус: он подтверждает
    ставку, а не формулировку статьи, поэтому текст нормы остаётся пустым и
    сверка пересказа для такой ссылки не выполняется.
    """
    result = lookup_article("НК РК", "665")

    assert result.found is True
    assert result.verified is True
    assert result.source_hash
    assert result.source_url.startswith("https://adilet.zan.kz/")
    assert result.text == ""


def test_rate_registry_does_not_license_other_articles() -> None:
    """Справочник ставок подтверждает одну норму, а не весь Налоговый кодекс."""
    result = lookup_article("НК РК", "664")

    assert result.verified is False


def test_state_duty_line_keeps_its_article_and_is_traced(corpus) -> None:
    draft = _draft(
        state_duty="239 558 тенге (3% от цены иска; максимум 20 000 МРП; статья 665 Налогового кодекса РК)",
        legal_basis=[],
    )

    report = enforce_article_authority(draft)

    assert "665" in draft.state_duty
    assert any(row["article"] == "665" for row in report.traceability())
