"""Обязательные проверки применимости нормы во времени и по кругу отношений.

Каждый случай здесь — довод, который суд снимает целиком: статья, введённая
после спорного договора; редакция, изменившаяся к моменту подачи; общая норма
там, где действует специальная; потребительская норма в споре двух компаний;
статья с сайта-перепечатки. В тексте иска все они выглядят одинаково уверенно,
поэтому отличить их обязан код, а не читающий.
"""

from __future__ import annotations

from datetime import date

from korgan.temporal_law import (
    LegalDates,
    LegalSourceStatus,
    NormKind,
    NormVersion,
    check_applicable_law,
    check_norm,
    kind_of_act,
    relationship_date_in_text,
)

ADILET = "https://adilet.zan.kz/rus/docs/K990000409_"

# Спор из договора 2019 года, иск подаётся в 2026-м.
CASE = LegalDates(
    relationship_started=date(2019, 5, 10),
    contract_signed=date(2019, 5, 10),
    performance_due=date(2019, 7, 1),
    breach=date(2019, 7, 2),
    claim_sent=date(2026, 6, 1),
    filing=date(2026, 9, 1),
)


def norm(**kwargs) -> NormVersion:
    options = {
        "act": "ГК РК",
        "article": "353",
        "source_url": ADILET,
        "in_force_from": date(1999, 7, 1),
    }
    options.update(kwargs)
    return NormVersion(**options)


# 1. Норма действует сегодня, но не действовала на дату события.

def test_norm_introduced_after_the_relationship_is_not_applicable() -> None:
    """Статья 2021 года не регулирует договор 2019 года."""
    check = check_norm(norm(article="399-1", in_force_from=date(2021, 1, 1)), CASE)

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert check.governing_date == date(2019, 5, 10)
    assert any("введена в действие 01.01.2021" in reason for reason in check.reasons)


# 2. Применяется старая редакция статьи.

def test_the_superseded_redaction_is_applicable_when_it_is_named() -> None:
    """К старому договору применяется старая редакция — если она названа."""
    check = check_norm(
        norm(
            in_force_from=date(2015, 1, 1),
            in_force_to=date(2021, 12, 31),
            redaction="в редакции Закона РК от 27.02.2017 № 49-VI",
        ),
        CASE,
    )

    assert check.status is LegalSourceStatus.VERIFIED


# 3. Норма изменилась между заключением договора и подачей иска.

def test_amended_norm_without_a_named_redaction_is_blocked() -> None:
    """Без указания редакции читающий сверит ссылку с действующим текстом
    и не найдёт совпадения."""
    check = check_norm(
        norm(in_force_from=date(2015, 1, 1), in_force_to=date(2021, 12, 31)), CASE
    )

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert any("не указана применяемая редакция" in reason for reason in check.reasons)


# 4. Общая норма против специальной.

def test_special_norm_displaces_the_general_one() -> None:
    general = norm(article="9", act="ГК РК")
    special = norm(
        article="428",
        act="ГК РК",
        special_to="статьи 9 ГК РК",
    )
    result = check_applicable_law([general, special], CASE)

    assert result.ready is False
    assert any("является специальной по отношению" in reason for reason in result.reasons)


# 5. Физическое лицо, которое не является потребителем.

def test_consumer_norm_does_not_cover_a_business_purchase_by_an_individual() -> None:
    """Физлицо, покупающее для предпринимательской деятельности, потребителем
    не является, и потребительские гарантии на него не распространяются."""
    check = check_norm(
        norm(
            act="Закон РК «О защите прав потребителей»",
            article="14",
            covers=("защита прав потребителей",),
        ),
        CASE,
        relationship="предпринимательская деятельность",
    )

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert any("регулирует защита прав потребителей" in reason for reason in check.reasons)


# 6. Спор двух юридических лиц.

def test_two_companies_get_the_supply_norm_and_not_the_consumer_one() -> None:
    consumer = norm(
        act="Закон РК «О защите прав потребителей»",
        article="14",
        covers=("защита прав потребителей",),
    )
    supply = norm(article="458", covers=("поставка",))

    blocked = check_applicable_law([consumer], CASE, relationship="поставка")
    allowed = check_applicable_law([supply], CASE, relationship="поставка")

    assert blocked.ready is False
    assert allowed.ready is True


# 7. Ошибочная статья, предложенная пользователем.

def test_article_proposed_by_the_client_is_checked_against_the_dispute() -> None:
    """Клиент назвал статью о моральном вреде в споре о поставке."""
    check = check_norm(
        norm(article="951", covers=("возмещение морального вреда",)),
        CASE,
        relationship="поставка",
    )

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION


# 8. Несуществующая статья.

def test_article_without_a_source_and_without_a_start_date_is_not_asserted() -> None:
    """Статьи, которой нет, нет и в официальном источнике: подтвердить её
    нечем, и в документ она не попадает."""
    check = check_norm(
        NormVersion(act="ГК РК", article="9999"),
        CASE,
    )

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert any("официальным источником" in reason for reason in check.reasons)
    assert any("введения нормы в действие" in reason for reason in check.reasons)


# 9. Норма из неофициального интернет-источника.

def test_a_reprint_on_another_site_is_not_an_official_source() -> None:
    """Перепечатка выглядит так же, но не отражает ни редакцию, ни утрату силы."""
    check = check_norm(norm(source_url="https://online.zakon.kz/Document/?doc_id=1006061"), CASE)

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert any("adilet.zan.kz" in reason for reason in check.reasons)


# 10. Данных для определения применимого права недостаточно.

def test_without_legally_significant_dates_the_law_cannot_be_established() -> None:
    check = check_norm(norm(), LegalDates())

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert check.governing_date is None
    assert any("не установлена дата" in reason for reason in check.reasons)


# Материальная и процессуальная норма определяются разными датами.

def test_procedural_norm_is_judged_by_the_filing_date_not_the_contract_date() -> None:
    """ГПК применяется в редакции на день совершения процессуального действия,
    поэтому норма 2023 года годится для иска 2026 года по договору 2019-го."""
    procedural = check_norm(
        norm(act="ГПК РК", article="148", in_force_from=date(2023, 1, 1),
             kind=NormKind.PROCEDURAL),
        CASE,
    )
    substantive = check_norm(norm(article="399-1", in_force_from=date(2023, 1, 1)), CASE)

    assert procedural.status is LegalSourceStatus.VERIFIED
    assert procedural.governing_date == date(2026, 9, 1)
    assert substantive.status is LegalSourceStatus.NEEDS_VERIFICATION


def test_a_document_without_any_norm_is_not_ready() -> None:
    result = check_applicable_law([], CASE)

    assert result.ready is False
    assert any("применимое право не установлено" in reason for reason in result.reasons)


def test_transitional_provisions_are_decided_by_a_lawyer() -> None:
    check = check_norm(norm(transitional="статья 3 Закона о введении в действие"), CASE)

    assert check.status is LegalSourceStatus.NEEDS_VERIFICATION
    assert any("переходные положения" in reason for reason in check.reasons)


def test_a_verified_norm_passes_the_gate() -> None:
    result = check_applicable_law([norm(covers=("поставка",))], CASE, relationship="поставка")

    assert result.ready is True
    assert result.reasons == ()


# --- дата, на которую сверяется редакция, берётся из самого документа ---


def test_the_release_note_names_the_relationship_date_not_the_filing_date() -> None:
    """Материальную норму сверяют на дату правоотношения, а не на дату подачи.

    Указание сверить статью «с действующей редакцией на дату подачи» выглядит
    выполненным и уводит проверяющего от единственной даты, которая здесь
    решает исход довода."""
    from korgan.document_release import review_document

    report = review_document(
        "По договору поставки № 12 от 10 мая 2019 года ответчик обязался оплатить товар. "
        "Требование основано на статье 353 ГК РК."
    )
    note = next(item for item in report.checklist() if "Сверьте каждую статью" in item)

    assert "10.05.2019" in note
    assert "дату возникновения спорного правоотношения" in note
    assert "процессуальные нормы — в редакции на дату подачи" in note


def test_a_document_without_a_contract_date_gets_the_general_wording() -> None:
    """Дата не найдена — указание остаётся общим. Догадка выглядела бы
    установленным фактом, и её больше никто не перепроверил бы."""
    from korgan.document_release import review_document

    report = review_document("Требование основано на статье 353 ГК РК.")
    note = next(item for item in report.checklist() if "Сверьте каждую статью" in item)

    assert "дату возникновения спорного правоотношения" in note
    assert not any(char.isdigit() for char in note.split("(")[0].replace("353", ""))


def test_the_checklist_splits_the_articles_by_the_date_each_is_checked_against() -> None:
    """Материальные и процессуальные статьи сверяются на разные даты.

    Общее указание оставляло это решение читающему, а решение неочевидное:
    в тексте иска статья 353 ГК и статья 148 ГПК стоят рядом и выглядят
    одинаково. Сверить их на одну дату — значит для одной из них получить
    подтверждение не той редакции, причём выглядящее полноценным.
    """
    from korgan.document_release import SPLIT_NOTE_PREFIX, review_document

    report = review_document(
        "По договору поставки № 12 от 10 мая 2019 года ответчик обязался оплатить товар. "
        "Требование основано на статье 353 ГК РК. "
        "Иск подаётся по правилам статьи 148 ГПК РК."
    )
    note = next(item for item in report.checklist() if item.startswith(SPLIT_NOTE_PREFIX))

    substantive, procedural = note.split(";")
    assert "353" in substantive and "10.05.2019" in substantive
    assert "148" in procedural and "на дату подачи" in procedural
    # Процессуальная статья не должна попасть в группу с датой договора:
    # её редакция определяется днём подачи, и сверка на 2019 год неверна.
    assert "148" not in substantive


def test_a_document_citing_only_one_kind_of_norm_gets_no_extra_line() -> None:
    """Разбивка на группы имеет смысл, только если групп две.

    Список из одной группы повторяет общее указание другими словами. Лишняя
    строка в чек-листе стоит внимания читающего, а внимание здесь — ресурс:
    чек-лист, который длиннее нужного, начинают просматривать по диагонали.
    """
    from korgan.document_release import SPLIT_NOTE_PREFIX, review_document

    report = review_document(
        "Договор поставки от 10 мая 2019 года. Требование основано на статье 353 ГК РК."
    )

    assert not any(item.startswith(SPLIT_NOTE_PREFIX) for item in report.checklist())


def test_an_unknown_act_is_treated_as_substantive() -> None:
    """Ошибка в эту сторону велит сверить норму на более раннюю дату — лишняя
    работа. Ошибка в другую молча подтвердила бы сегодняшнюю редакцию для
    старого договора, и это уже неверное применимое право."""
    assert kind_of_act("Закон РК «О товариществах»") is NormKind.SUBSTANTIVE
    assert kind_of_act("ГК РК") is NormKind.SUBSTANTIVE
    assert kind_of_act("ГПК РК") is NormKind.PROCEDURAL


def test_a_birth_date_is_not_mistaken_for_the_relationship_date() -> None:
    assert relationship_date_in_text("Истец родился 01.01.1980. Претензия направлена 01.06.2026.") is None


def test_the_earliest_contract_governs_when_there_are_several() -> None:
    text = (
        "Между сторонами заключён договор поставки от 10.05.2019 и договор "
        "поставки № 2 от 15.03.2021."
    )

    assert relationship_date_in_text(text) == date(2019, 5, 10)
