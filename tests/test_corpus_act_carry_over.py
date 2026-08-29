"""Недоступный акт не должен исчезать из корпуса норм.

Что случилось на проде 29.08.2026
---------------------------------
    WARNING corpus_refresh: act=ZPP_RK НЕ загружен: Both official sources failed
    RuntimeError: Частичная сборка (5441 норм, актов 5/6) беднее существующего
                  корпуса (5627 норм); живой корпус сохранён

Живой корпус уцелел — но только потому, что арифметика случайно сошлась.
Проверка сравнивает суммы ПО ВСЕМУ корпусу: стоило бы ГК РК в новой редакции
прибавить две сотни норм, и 5441 превратилось бы в 5641, подмена прошла бы, а
Закон «О защите прав потребителей» молча исчез бы из корпуса.

Цена исчезновения конкретная. Гейт цитат отвечает «норма нашлась / не
нашлась». Без акта ни одна ссылка на него не подтверждается, и каждый
потребительский иск выходит «предварительным проектом» — при том, что написан
он правильно.

Эти тесты фиксируют три требования:
* недоступный акт переносится из живого корпуса, а не теряется;
* внезапно усечённый акт считается усечением ответа, а не поправкой;
* оборванное соединение переспрашивается, но недочитанный текст закона
  не принимается никогда.
"""

from __future__ import annotations

import http.client
from pathlib import Path

import pytest

from korgan.legal.corpus import KNOWN_ACTS, LegalCorpus
from korgan.legal.corpus_refresh import refresh_corpus_once

CONSUMER_ACT = "ZPP_RK"


def _seed_live_corpus(target: Path, counts: dict[str, int]) -> None:
    """Положить живой корпус с заданным числом норм по каждому акту."""
    with LegalCorpus(target) as corpus:
        for act_id, count in counts.items():
            adilet_id, title = KNOWN_ACTS[act_id]
            url = f"https://adilet.zan.kz/rus/docs/{adilet_id}"
            corpus.upsert_act(
                act_id=act_id,
                adilet_id=adilet_id,
                title_ru=title,
                url=url,
                edition_date="2026-07-01",
                loaded_at="2026-07-01",
            )
            for index in range(count):
                corpus.upsert_provision(
                    act_id=act_id,
                    article_no=str(index + 1),
                    item_no=None,
                    heading=f"Статья {index + 1}",
                    body=f"Текст статьи {index + 1} акта {act_id} достаточной длины для корпуса.",
                    edition_date="2026-07-01",
                    url=f"{url}#z{index + 1}",
                    sort_key=index,
                )
        corpus.connection.commit()


def _loader(per_act: dict[str, int], *, default: int = 1):
    """Заглушка load_act: кладёт заданное число норм и возвращает его."""

    def load(corpus, act_id, html, *, url=None, edition_date=None, articles=None):
        adilet_id, title = KNOWN_ACTS[act_id]
        target_url = url or f"https://adilet.zan.kz/rus/docs/{adilet_id}"
        corpus.upsert_act(
            act_id=act_id,
            adilet_id=adilet_id,
            title_ru=title,
            url=target_url,
            edition_date="2026-08-29",
            loaded_at="2026-08-29",
        )
        count = per_act.get(act_id, default)
        for index in range(count):
            corpus.upsert_provision(
                act_id=act_id,
                article_no=str(index + 1),
                item_no=None,
                heading=f"Статья {index + 1}",
                body=f"Свежий текст статьи {index + 1} акта {act_id} достаточной длины.",
                edition_date="2026-08-29",
                url=f"{target_url}#z{index + 1}",
                sort_key=index,
            )
        return count

    return load


def _fail_for(act_ids: set[str], refresh):
    """fetch_adilet, падающий только на указанных актах."""

    def fetch(url: str, timeout: int = 60):
        act_id = refresh._act_id_for_adilet_url(url)
        if act_id in act_ids:
            raise RuntimeError("Adilet оборвал ответ 3 раза подряд: IncompleteRead")
        return "<html>official</html>", url

    return fetch


@pytest.fixture()
def refresh_module():
    import korgan.legal.corpus_refresh as refresh

    return refresh


def test_unavailable_act_is_carried_over_from_the_live_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    target = tmp_path / "corpus.sqlite3"
    _seed_live_corpus(target, {act_id: 5 for act_id in KNOWN_ACTS})

    monkeypatch.setattr(refresh_module, "fetch_adilet", _fail_for({CONSUMER_ACT}, refresh_module))
    monkeypatch.setattr(
        refresh_module,
        "fetch_zan",
        lambda act_id, timeout=90: (_ for _ in ()).throw(RuntimeError("zan unavailable")),
    )
    monkeypatch.setattr(refresh_module, "load_act", _loader({}, default=5))

    refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count(CONSUMER_ACT) == 5, "закон о защите прав потребителей исчез из корпуса"
        row = corpus.connection.execute(
            "SELECT edition_date FROM acts WHERE act_id = ?", (CONSUMER_ACT,)
        ).fetchone()
        # Перенесённый акт честно сохраняет прежнюю дату редакции: документ
        # должен показывать, на какую версию он опирается.
        assert row["edition_date"] == "2026-07-01"


def test_growth_of_another_act_no_longer_masks_a_lost_act(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Ровно тот сценарий, который проверка по общей сумме не ловила.

    ЗПП РК недоступен (−5 норм), а ГК РК в новой редакции прибавил (+50).
    Сумма растёт, подмена проходит — и раньше акт исчезал бы бесследно.
    """
    target = tmp_path / "corpus.sqlite3"
    _seed_live_corpus(target, {act_id: 5 for act_id in KNOWN_ACTS})
    grown = next(act_id for act_id in sorted(KNOWN_ACTS) if act_id != CONSUMER_ACT)

    monkeypatch.setattr(refresh_module, "fetch_adilet", _fail_for({CONSUMER_ACT}, refresh_module))
    monkeypatch.setattr(
        refresh_module,
        "fetch_zan",
        lambda act_id, timeout=90: (_ for _ in ()).throw(RuntimeError("zan unavailable")),
    )
    monkeypatch.setattr(refresh_module, "load_act", _loader({grown: 55}, default=5))

    total = refresh_corpus_once(target)

    assert total > 5 * len(KNOWN_ACTS), "сценарий не воспроизведён: сумма должна была вырасти"
    with LegalCorpus(target) as corpus:
        assert corpus.count(grown) == 55
        assert corpus.count(CONSUMER_ACT) == 5, "рост соседнего акта скрыл потерю ЗПП РК"


def test_a_sharply_truncated_act_keeps_its_previous_edition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Недочитанный ответ приходит как «успех» — и опаснее явного отказа."""
    target = tmp_path / "corpus.sqlite3"
    _seed_live_corpus(target, {act_id: 100 for act_id in KNOWN_ACTS})

    monkeypatch.setattr(
        refresh_module, "fetch_adilet", lambda url, timeout=60: ("<html>official</html>", url)
    )
    # Акт отдался, но в нём осталась четверть статей — это обрыв ответа.
    monkeypatch.setattr(refresh_module, "load_act", _loader({CONSUMER_ACT: 25}, default=100))

    refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count(CONSUMER_ACT) == 100, "усечённый акт подменил полную редакцию"
        row = corpus.connection.execute(
            "SELECT edition_date FROM acts WHERE act_id = ?", (CONSUMER_ACT,)
        ).fetchone()
        assert row["edition_date"] == "2026-07-01"


def test_a_normal_amendment_still_replaces_the_act(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Защита от усечения не должна мешать обычной отмене статей."""
    target = tmp_path / "corpus.sqlite3"
    _seed_live_corpus(target, {act_id: 100 for act_id in KNOWN_ACTS})

    monkeypatch.setattr(
        refresh_module, "fetch_adilet", lambda url, timeout=60: ("<html>official</html>", url)
    )
    monkeypatch.setattr(refresh_module, "load_act", _loader({CONSUMER_ACT: 95}, default=100))

    refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count(CONSUMER_ACT) == 95
        row = corpus.connection.execute(
            "SELECT edition_date FROM acts WHERE act_id = ?", (CONSUMER_ACT,)
        ).fetchone()
        assert row["edition_date"] == "2026-08-29"


def test_an_act_absent_from_the_live_corpus_is_simply_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Переносить нечего — это не ошибка, остальные акты продолжают грузиться."""
    target = tmp_path / "corpus.sqlite3"
    _seed_live_corpus(target, {act_id: 5 for act_id in KNOWN_ACTS if act_id != CONSUMER_ACT})

    monkeypatch.setattr(refresh_module, "fetch_adilet", _fail_for({CONSUMER_ACT}, refresh_module))
    monkeypatch.setattr(
        refresh_module,
        "fetch_zan",
        lambda act_id, timeout=90: (_ for _ in ()).throw(RuntimeError("zan unavailable")),
    )
    monkeypatch.setattr(refresh_module, "load_act", _loader({}, default=5))

    refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count(CONSUMER_ACT) == 0
        assert corpus.count() == 5 * (len(KNOWN_ACTS) - 1)


def test_a_dropped_connection_is_retried_before_the_act_is_given_up(
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    attempts = 0

    def flaky(url, *, context, act_id, timeout=60):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise http.client.IncompleteRead(b"x" * 44742)
        return "<html>official</html>", url

    monkeypatch.setattr(refresh_module, "_read_https", flaky)
    monkeypatch.setattr(refresh_module.time, "sleep", lambda _seconds: None)

    text, _url = refresh_module._read_with_retry(
        "https://adilet.zan.kz/rus/docs/Z100000274_",
        context=None,
        act_id=CONSUMER_ACT,
        timeout=60,
        label="test",
    )

    assert attempts == 2
    assert text == "<html>official</html>"


def test_a_truncated_response_is_never_accepted_as_the_text_of_an_act(
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Половина закона, принятая за весь закон, — худший из возможных исходов."""

    def always_truncated(url, *, context, act_id, timeout=60):
        raise http.client.IncompleteRead(b"<html>half of the act</html>")

    monkeypatch.setattr(refresh_module, "_read_https", always_truncated)
    monkeypatch.setattr(refresh_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError) as error:
        refresh_module._read_with_retry(
            "https://adilet.zan.kz/rus/docs/Z100000274_",
            context=None,
            act_id=CONSUMER_ACT,
            timeout=60,
            label="test",
        )

    assert "обрыв ответа" in str(error.value)
    assert "half of the act" not in str(error.value)


def test_a_tls_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    refresh_module,
) -> None:
    """Отказ TLS — устойчивое состояние; повтор только тратит время сборки."""
    attempts = 0

    def refuses(url, *, context, act_id, timeout=60):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(refresh_module, "_read_https", refuses)
    monkeypatch.setattr(refresh_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError):
        refresh_module._read_with_retry(
            "https://adilet.zan.kz/rus/docs/Z100000274_",
            context=None,
            act_id=CONSUMER_ACT,
            timeout=60,
            label="test",
        )

    assert attempts == 1
