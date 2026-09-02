"""Объявленная и незаполненная переменная окружения не должна ронять сервис.

Так выглядела авария в production. В Railway были заведены
`FREE_CONSULTATIONS_PER_DAY` и `CONSULTATION_PRICE_KZT` без значений — обе
пустые. Пустая строка приходит в `Settings` как ввод, для числового поля
pydantic считает её неверной и валит построение настроек целиком. Падал не тот
код, который эти две настройки использует, — падал импорт `Settings`, то есть
весь сервис, из-за двух величин с рабочими умолчаниями, которые никто не
собирался менять.

Хуже была форма отказа. Deploy падал на predeploy-тестах, production продолжал
отдавать прошлый образ и отвечать на `/health` — снаружи это неотличимо от
потерянной связи с GitHub. Диагноз ушёл в сторону, а причина всё это время
была в двух пустых строках.

Здесь зафиксировано и то, что пустое число возвращается к умолчанию, и то, где
эта снисходительность заканчивается: опечатка, обязательное поле и строковые
настройки остаются нетронутыми. Единственное отдельное правило безопасности —
пустой allowlist юридических источников не снимает ограничение поиска и не
превращается в невалидный пустой фильтр провайдера.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from korgan.config import Settings


class _SettingsWithRequiredNumber(Settings):
    """Настройки с обязательным числом — такого поля в самом `Settings` нет.

    Проверять границу снисходительности всё равно нужно: поле без умолчания
    может появиться завтра, и подстановка выдуманного числа в этот момент не
    должна оказаться уже разрешённой.
    """

    court_fee_kzt: int


def test_the_two_empty_variables_that_took_production_down(monkeypatch) -> None:
    """Дословно то, что стояло в Railway."""
    monkeypatch.setenv("FREE_CONSULTATIONS_PER_DAY", "")
    monkeypatch.setenv("CONSULTATION_PRICE_KZT", "")

    settings = Settings()

    assert settings.free_consultations_per_day == 5
    assert settings.consultation_price_kzt == 1000


def test_a_variable_of_spaces_is_still_an_empty_variable(monkeypatch) -> None:
    """Пробел в поле веб-формы Railway не виден глазом и ничего не значит."""
    monkeypatch.setenv("CONSULTATION_PRICE_KZT", "   ")

    assert Settings().consultation_price_kzt == 1000


def test_an_empty_flag_and_an_empty_fraction_behave_the_same_way(monkeypatch) -> None:
    """У флага и дроби пустого написания тоже нет.

    «» — это не «выключено» и не ноль; ноль в бюджете означал бы запрет любых
    вызовов AI, а это совсем другое решение, чем незаполненная настройка.
    """
    monkeypatch.setenv("PAYMENTS_ENABLED", "")
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "")
    monkeypatch.setenv("TOKEN_BUDGET_GUARD_ENABLED", "")

    settings = Settings()

    assert settings.payments_enabled is False
    assert settings.monthly_ai_budget_usd == 10.0
    # Умолчание, а не «пусто значит выключено»: страж бюджета включён по
    # умолчанию, и пустая переменная не должна его снимать.
    assert settings.token_budget_guard_enabled is True


def test_a_real_value_is_still_read(monkeypatch) -> None:
    """Снисходительность к пустоте не должна съедать заданные значения."""
    monkeypatch.setenv("FREE_CONSULTATIONS_PER_DAY", "3")
    monkeypatch.setenv("MONTHLY_AI_BUDGET_USD", "42.5")

    settings = Settings()

    assert settings.free_consultations_per_day == 3
    assert settings.monthly_ai_budget_usd == 42.5


def test_a_typo_is_still_an_error(monkeypatch) -> None:
    """Непустой мусор — это заданное значение, и оно должно быть отвергнуто.

    Иначе `FREE_CONSULTATIONS_PER_DAY=пять` тихо превратилось бы в 5, и
    оператор, ошибившийся в значении, никогда бы об этом не узнал.
    """
    monkeypatch.setenv("FREE_CONSULTATIONS_PER_DAY", "пять")

    with pytest.raises(ValidationError, match="free_consultations_per_day"):
        Settings()


def test_an_empty_string_setting_stays_an_empty_string(monkeypatch) -> None:
    """Для строк пустота — законное значение, а не отсутствие значения.

    Незаданный ключ, незаполненный БИН, пустая ссылка на оплату так и
    объявлены: `""`. Подстановка сюда «умолчания» ничего бы не изменила, но
    правило, применённое к строкам вообще, сделало бы пустой
    `ANTHROPIC_API_KEY` неотличимым от отсутствующего в тех местах, где
    умолчание непустое.
    """
    monkeypatch.setenv("KASPI_SELLER_BIN", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")

    settings = Settings()

    assert settings.kaspi_seller_bin == ""
    # Умолчание `claude-sonnet-5` не возвращается: оператор стёр значение сам.
    assert settings.anthropic_model == ""


def test_blank_legal_domains_keep_the_official_source_allowlist(monkeypatch) -> None:
    """Пустая Railway-строка не снимает ограничение юридического поиска.

    OpenAI отвергает пустой web-search filter, а удалять filters целиком нельзя:
    это разрешило бы юридическому исследованию ходить по всему интернету.
    Поэтому эффективный allowlist возвращается к узкому безопасному набору
    официальных источников, даже если сырая строковая настройка осталась пустой.
    """
    monkeypatch.setenv("OFFICIAL_LEGAL_DOMAINS", "   ")

    settings = Settings()

    assert settings.official_legal_domains == "   "
    assert settings.legal_domains == ["adilet.zan.kz", "gov.kz", "sud.gov.kz"]


def test_a_required_number_is_never_invented(monkeypatch) -> None:
    """Число, которого никто не назвал, ушло бы в расчёт как настоящее.

    Отказ построить настройки здесь правильный: у обязательного поля нет
    умолчания, а придумывать величину, попадающую в сумму иска, нельзя ни при
    каких обстоятельствах.
    """
    monkeypatch.setenv("COURT_FEE_KZT", "")

    with pytest.raises(ValidationError, match="court_fee_kzt"):
        _SettingsWithRequiredNumber()
