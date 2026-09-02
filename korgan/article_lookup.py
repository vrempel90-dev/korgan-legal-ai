"""Контракт поиска нормы: номер статьи разрешён только подтверждённым lookup.

Зачем модуль существует
-----------------------
Номер статьи в судебном документе — утверждение о действующем праве, которое
проверяет судья и опровергает противная сторона. Модель называет номер по
памяти: для изменённой статьи это номер прежней редакции, для несуществующей —
правдоподобное число. Проверить его по тексту документа нельзя, потому что
неверный номер выглядит ровно так же, как верный.

Здесь номер превращается в структурированный результат поиска. У результата
есть три состояния, и они licensing разные вещи:

* ``found=False`` — нормы нет ни в одном подтверждённом источнике. Номер не
  печатается.
* ``found=True, verified=False`` — запись существует, но не прочитана с
  официального источника (реестр со слов оператора). Номер не печатается.
* ``found=True, verified=True`` — текст нормы прочитан с официального
  источника. Только тогда номер попадает в документ, и вместе с ним —
  ``source_hash``, по которому напечатанное упоминание связывается с конкретной
  записью корпуса.

``source_hash`` считается от текста нормы, а не от её номера. Смысл в этом:
при обновлении корпуса номер остаётся прежним, а редакция меняется, и хэш
показывает, что документ ссылался на другой текст.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable

from korgan.provision_corpus import ProvisionRecord, normalize_text

#: Акты, о которых KORGAN вообще берётся утверждать что-либо в судебном тексте.
KNOWN_CODES: tuple[str, ...] = ("ГК РК", "ГПК РК", "НК РК", "ТК РК", "ЗПП РК", "КАС РК", "КоАП РК")

#: Отсылочная норма: её текст не устанавливает правило, а отправляет к другому.
#: Такая норма не может быть единственным основанием материального требования —
#: правило создаёт та статья, к которой она отсылает.
_REFERRAL_RE = re.compile(
    r"применя(?:ю|е)тся\s+(?:правила|положения|нормы)|"
    r"регулиру(?:ю|е)тся\s+(?:правилами|положениями|нормами)|"
    r"в\s+соответствии\s+с\s+правилами\s+(?:о|об)\s|"
    r"если\s+иное\s+не\s+(?:предусмотрено|установлено)\s+(?:правилами|настоящим\s+параграфом)",
    re.IGNORECASE,
)


def source_hash(text: str) -> str:
    """Устойчивый отпечаток текста нормы.

    Нормализация снимает различия набора — пробелы, «ё», кавычки, тире, — чтобы
    один и тот же текст, пришедший из SQLite-корпуса и из JSON-реестра, дал
    один отпечаток. Всё остальное отличие считается изменением редакции.
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class LookupResult:
    """Результат поиска одной нормы. Печатать номер разрешает только ``verified``."""

    found: bool
    verified: bool
    code: str
    article: str
    part: str = ""
    source_hash: str = ""
    text: str = ""
    source_url: str = ""
    edition_date: str = ""
    origin: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.verified and not self.found:
            raise ValueError("норма не найдена, но объявлена подтверждённой")
        if self.verified and not self.source_hash:
            raise ValueError("подтверждённая норма обязана нести source_hash")
        if not self.verified and not self.reason:
            raise ValueError("неподтверждённая норма обязана называть причину")

    @property
    def label(self) -> str:
        part = f"пункт {self.part} статьи " if self.part else "статья "
        return f"{part}{self.article} {self.code}".strip()

    @property
    def is_referral(self) -> bool:
        """Отсылает ли норма к другим правилам вместо того, чтобы их устанавливать."""
        return bool(self.text) and bool(_REFERRAL_RE.search(self.text))

    def as_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "verified": self.verified,
            "code": self.code,
            "article": self.article,
            "part": self.part,
            "source_hash": self.source_hash,
            "source_url": self.source_url,
            "edition_date": self.edition_date,
            "origin": self.origin,
            "reason": self.reason,
        }


def not_found(code: str, article: str, part: str = "", *, reason: str = "") -> LookupResult:
    return LookupResult(
        found=False,
        verified=False,
        code=code,
        article=article,
        part=part,
        reason=reason or (
            f"статьи {article} {code} нет ни в локальном корпусе Adilet, "
            "ни в source-bound VERIFIED текущего документа"
        ),
    )


def from_record(code: str, article: str, part: str, record: ProvisionRecord, *, origin: str) -> LookupResult:
    """Превратить запись корпуса в результат поиска.

    Запись уровня REPORTED даёт ``found`` без ``verified``: она попала в реестр
    со слов оператора, официальный источник её не подтверждал. Номер статьи по
    такой записи в документ не идёт — при том, что сама запись остаётся полезной
    для внутренней работы юриста.
    """
    text = " ".join(str(record.text or "").split())
    if not record.citable_verbatim:
        return LookupResult(
            found=True,
            verified=False,
            code=code,
            article=article,
            part=part,
            source_hash=source_hash(text) if text else "",
            text=text,
            source_url=record.source_url,
            edition_date=record.verified_on,
            origin=origin,
            reason=(
                f"запись о статье {article} {code} не прочитана с официального источника "
                f"({record.provenance or 'происхождение не указано'})"
            ),
        )
    return LookupResult(
        found=True,
        verified=True,
        code=code,
        article=article,
        part=part,
        source_hash=source_hash(text),
        text=text,
        source_url=record.source_url,
        edition_date=record.verified_on,
        origin=origin,
    )


#: Тип функции поиска. Инъекция нужна не только тестам: боевой рантайм
#: подменяет источник корпуса через client_safe_ui, и модуль не должен знать,
#: какой именно источник подключён в этом процессе.
LookupFn = Callable[[str, str, str], "LookupResult"]


def _lookup_local_corpus(code: str, article: str, part: str) -> ProvisionRecord | None:
    """Найти норму в SQLite-корпусе, открыв его на время поиска.

    Соединение не кэшируется намеренно. ``corpus_bridge`` держит одно соединение
    на процесс — это верно для боевого рантайма, где путь к корпусу задан один
    раз, и неверно здесь: тот же кэш переживает подмену пути к базе и отвечает
    из корпуса, собранного для другого дела. Открыть базу заново стоит доли
    миллисекунды, а ответ из чужого корпуса стоит неверной ссылки в иске.
    """
    try:
        from korgan.corpus_bridge import _ACT_TO_CORPUS_IDS, _ITEM_RE, _to_record
        from korgan.legal.corpus import make_article_id
        from korgan.legal.pipeline import local_corpus_enabled, open_corpus
    except Exception:  # pragma: no cover - корпус не собран в этой сборке
        return None

    if not local_corpus_enabled():
        return None

    act_ids = _ACT_TO_CORPUS_IDS.get((code or "").strip())
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

    corpus = None
    try:
        corpus = open_corpus()
        if corpus is None:
            return None
        for act_id in act_ids:
            # Сначала точный пункт, затем статья целиком: ссылка на пункт должна
            # найтись и тогда, когда корпус хранит статью неразбитой.
            for candidate_item in ([item_no, None] if item_no else [None]):
                provision = corpus.get(make_article_id(act_id, article_no, candidate_item))
                if provision is not None:
                    return _to_record(code, article_no, part if candidate_item else "", provision)
    except Exception:  # pragma: no cover - сбой источника не подтверждает норму
        return None
    finally:
        if corpus is not None:
            corpus.close()
    return None


def lookup_article(code: str, article: str, part: str = "") -> LookupResult:
    """Найти норму в подтверждённых источниках KORGAN.

    Источники опрашиваются в порядке убывания достоверности: локальный корпус
    Adilet, прочитанный загрузчиком с официальной страницы, затем ручной реестр
    провизий. Отсутствие корпуса — не повод считать норму подтверждённой: без
    источника результат остаётся ``found=False``, и номер не печатается.
    """
    normalized = (code or "").strip()
    if normalized not in KNOWN_CODES:
        return not_found(
            normalized or "неизвестный акт",
            article,
            part,
            reason=f"акт «{normalized or 'не назван'}» не входит в проверяемый корпус KORGAN",
        )

    from korgan import provision_corpus

    record = _lookup_local_corpus(normalized, article, part)
    if record is not None:
        return from_record(normalized, article, part, record, origin="локальный корпус Adilet")

    record = provision_corpus.lookup(normalized, article, part)
    if record is not None:
        return from_record(normalized, article, part, record, origin="реестр провизий KORGAN")

    return not_found(normalized, article, part)
