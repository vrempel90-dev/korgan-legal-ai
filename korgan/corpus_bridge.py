"""Мост между гейтом цитат и загруженным корпусом НПА.

Дефект, который закрывает этот модуль
--------------------------------------
В KORGAN два разных хранилища норм:

* `korgan/data/provisions.json` — ручной реестр `provision_corpus`. В нём одна
  запись: часть 2 статьи 166 ГПК РК, да и та уровня REPORTED.
* `korgan/data/corpus.sqlite3` — настоящий корпус `korgan.legal.corpus`,
  который при каждом старте грузится с adilet. В проде это шесть актов и
  5 627 положений:

      KORGAN corpus progressive READY acts=6/6 provisions=5627 failures=0

`citation_audit.lookup` ходил только в первое. Поэтому любая статья, кроме
единственной записи из JSON, получала вердикт UNVERIFIABLE:

    текста нормы нет ни в source-bound VERIFIED текущего документа,
    ни в проверенном корпусе KORGAN

UNVERIFIABLE — блокирующий вердикт. Дальше `document_quality` выставлял
hard blocker «есть правовая ссылка, не прошедшая source-bound/corpus
проверку», оценка падала ниже порога 8.5, и релизный гейт не выпускал
документ. Это касалось не только исков: `review_lines` вызывается для
договора, отзыва на иск, претензии и ответа на претензию одинаково.

Единственный путь, по которому документ раньше мог выйти, — если строка
VERIFIED-исследования случайно попадала в точный формат
`текст нормы: «...»; источник: <adilet>`. То есть выпуск документа зависел
от того, как модель отформатировала служебную строку.

Здесь SQLite-корпус подключается как второй источник поиска. Записи из него
считаются VERIFIED: они прочитаны загрузчиком с официального источника,
дата сверки — дата загрузки акта.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from korgan.provision_corpus import VERIFIED, ProvisionRecord

LOGGER = logging.getLogger(__name__)

# Сокращение акта из текста документа -> идентификаторы актов в SQLite-корпусе.
# ГК РК разделён на две части, и в ссылке часть называют не всегда, поэтому
# ищем в обеих: номера статей у частей не пересекаются.
_ACT_TO_CORPUS_IDS: dict[str, tuple[str, ...]] = {
    "ГК РК": ("GK_RK_OBSHAYA", "GK_RK_OSOBENNAYA"),
    "ГПК РК": ("GPK_RK",),
    "НК РК": ("NK_RK_GOSPOSHLINA",),
    "ТК РК": ("TK_RK",),
    "ЗПП РК": ("ZPP_RK",),
}

_ACT_ALIASES: dict[str, tuple[str, ...]] = {
    "ГК РК": ("Гражданский кодекс Республики Казахстан", "ГК"),
    "ГПК РК": ("Гражданский процессуальный кодекс Республики Казахстан", "ГПК"),
    "НК РК": ("Налоговый кодекс Республики Казахстан", "НК"),
    "ТК РК": ("Трудовой кодекс Республики Казахстан", "ТК"),
    "ЗПП РК": ("Закон Республики Казахстан «О защите прав потребителей»",),
}

_ITEM_RE = re.compile(r"\d+(?:-\d+)?")

_lock = threading.Lock()
_corpus: Any = None
_corpus_ready = False


def _open_corpus() -> Any:
    """Открыть корпус один раз на процесс; отсутствие корпуса — не ошибка."""
    global _corpus, _corpus_ready
    if _corpus_ready:
        return _corpus
    with _lock:
        if _corpus_ready:
            return _corpus
        try:
            from korgan.legal.pipeline import open_corpus

            _corpus = open_corpus()
            if _corpus is not None:
                LOGGER.info("KORGAN citation bridge: локальный корпус подключён к проверке ссылок")
        except Exception:
            LOGGER.exception("KORGAN citation bridge: корпус недоступен, проверка ссылок работает без него")
            _corpus = None
        _corpus_ready = True
        return _corpus


def reset_cache() -> None:
    """Сбросить кэш соединения — нужно тестам и после перезагрузки корпуса."""
    global _corpus, _corpus_ready
    with _lock:
        if _corpus is not None:
            try:
                _corpus.close()
            except Exception:
                LOGGER.debug("KORGAN citation bridge: соединение с корпусом уже закрыто")
        _corpus = None
        _corpus_ready = False


def _to_record(act: str, article: str, part: str, provision: Any) -> ProvisionRecord:
    edition = str(getattr(provision, "edition_date", "") or "")
    return ProvisionRecord(
        act=act,
        act_aliases=_ACT_ALIASES.get(act, ()),
        article=str(article),
        part=str(part or ""),
        text=" ".join(str(getattr(provision, "body", "") or "").split()),
        source_url=str(getattr(provision, "url", "") or ""),
        verified_on=edition,
        # Запись прочитана загрузчиком напрямую с официального источника,
        # поэтому она citable_verbatim — в отличие от REPORTED-записей,
        # попавших в JSON со слов оператора.
        level=VERIFIED,
        provenance=(
            "Загружено в локальный корпус KORGAN с официального источника "
            f"{getattr(provision, 'url', '')} (редакция {edition or 'не указана'})."
        ),
    )


def lookup_in_local_corpus(act: str, article: str, part: str = "") -> ProvisionRecord | None:
    """Найти норму в SQLite-корпусе. None — если корпуса нет или нормы в нём нет."""
    corpus = _open_corpus()
    if corpus is None:
        return None

    act_ids = _ACT_TO_CORPUS_IDS.get((act or "").strip().upper().replace("  ", " "))
    if not act_ids:
        act_ids = _ACT_TO_CORPUS_IDS.get((act or "").strip())
    if not act_ids:
        return None

    article_no = str(article or "").strip()
    if not article_no:
        return None

    item_no = None
    if part:
        match = _ITEM_RE.search(str(part))
        if match:
            item_no = match.group(0)

    try:
        from korgan.legal.corpus import make_article_id

        for act_id in act_ids:
            # Сначала точный пункт, затем статья целиком: ссылка «часть 2
            # статьи 166» должна найтись и тогда, когда корпус хранит статью
            # неразбитой.
            for candidate_item in ([item_no, None] if item_no else [None]):
                provision = corpus.get(make_article_id(act_id, article_no, candidate_item))
                if provision is not None:
                    return _to_record(act, article_no, part if candidate_item else "", provision)
    except Exception:
        LOGGER.exception("KORGAN citation bridge: ошибка поиска %s %s в корпусе", act, article)
        return None
    return None
