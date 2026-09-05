"""Единственное место, где решается, какой документ готовится.

Что произошло в проде
---------------------
Клиент выбрал «Досудебная претензия», а получил ``KORGAN_otvet_na_pretenziyu.docx``
с заголовком «ОТВЕТ НА ПРЕТЕНЗИЮ» и перевёрнутыми ролями: кредитор оказался
адресатом, должник — отправителем. Документ, требующий оплату долга, превратился
в документ, которым должник отвечает кредитору.

Почему это случилось
--------------------
Тип документа определялся дважды: один раз — выбором пользователя, второй раз —
разбором свободного текста дела. Второй разбор не знал о первом. Фабула
обычной претензии почти всегда содержит слова «ответа на претензию не
поступило», а детектор ``is_pretrial_response_request`` искал сочетание
«ответ … на … претензию» в любом месте текста и любое слово-действие в любом
другом месте. Совпадение двух не связанных между собой кусков фабулы
переключало пайплайн на противоположный тип документа.

Правило
-------
1. Явный выбор (кнопка раздела, тип дела Mini App) — окончателен. Текст дела
   его не отменяет никогда: слова «договор», «претензия», «иск» описывают спор,
   а не то, что просят подготовить.
2. Свободный текст разбирается только тогда, когда выбора нет вовсе. При этом
   ``pretrial`` и ``pretrial_response`` взаимоисключающи: просьба подготовить
   ответ должна стоять рядом с глаголом-действием, и она проигрывает прямой
   просьбе подготовить саму претензию.
"""

from __future__ import annotations

import re

#: Пять типов документа. Порядок не важен, важен состав: любой тип вне набора
#: не должен доходить до конвейера, иначе он выберет ветку по умолчанию.
DOCUMENT_TYPES: frozenset[str] = frozenset(
    {"claim", "contract", "response", "pretrial", "pretrial_response"}
)

#: Роли сторон, зафиксированные для двух претензионных документов. Именно их
#: переворот и был виден клиенту.
PRETRIAL_SENDER_ROLE = "creditor"
PRETRIAL_RECIPIENT_ROLE = "debtor"
PRETRIAL_RESPONSE_SENDER_ROLE = "debtor"
PRETRIAL_RESPONSE_RECIPIENT_ROLE = "creditor"

ROLE_MATRIX: dict[str, dict[str, str]] = {
    "pretrial": {
        "sender": PRETRIAL_SENDER_ROLE,
        "recipient": PRETRIAL_RECIPIENT_ROLE,
    },
    "pretrial_response": {
        "sender": PRETRIAL_RESPONSE_SENDER_ROLE,
        "recipient": PRETRIAL_RESPONSE_RECIPIENT_ROLE,
    },
}

#: Слова-действия — просьба подготовить документ, а не рассказ о деле.
_ACTION = re.compile(
    r"(?i)\b(?:подготов\w*|состав\w*|сформир\w*|сдел\w*|напиш\w*|напис\w*|созда\w*|"
    r"сгенерир\w*|оформ\w*|разработ\w*|нуж(?:ен|на|но|ны|н\w*)|требуетс\w*|хочу\b|прош\w*|"
    r"дайында\w*|жаса\w*|әзірле\w*|құрастыр\w*|жаз\w*|қалыптастыр\w*|керек\b|қажет\b)\b"
)

#: «Ответ/возражение на претензию» как предмет просьбы.
_RESPONSE_NOUN = re.compile(
    r"(?i)(?:\bответ\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
    r"\bвозражен\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
    r"\bотзыв\w*\s+на\s+(?:досудебн\w*\s+)?претензи\w*|"
    r"сотқа\s+дейінгі\s+талап\w*\s+(?:жауап\w*|пікір\w*)|"
    r"талап\s+хат\w*\s+(?:жауап\w*|пікір\w*))"
)

#: Сама досудебная претензия как предмет просьбы.
_PRETRIAL_NOUN = re.compile(
    r"(?i)(?:\bдосудебн\w*\s+претензи\w*|\bпретензи\w*|"
    r"сотқа\s+дейінгі\s+талап\w*|талап\s+хат\w*)"
)

#: Расстояние, на котором глагол и существительное ещё читаются как одна
#: просьба. Подобрано по формулировкам клиентов: «подготовьте, пожалуйста,
#: досудебную претензию к ТОО …» укладывается, а глагол из соседнего абзаца —
#: уже нет.
_FORWARD_GAP = 120
_BACKWARD_GAP = 60


def _requested(text: str, noun: re.Pattern[str]) -> tuple[bool, int]:
    """Просят ли подготовить документ, названный ``noun``.

    Возвращает признак и позицию существительного: по позиции разрешается спор
    между «претензией» и «ответом на претензию», когда фабула упоминает оба.
    """
    value = " ".join((text or "").split())
    if not value:
        return False, -1

    best = -1
    for action in _ACTION.finditer(value):
        for match in noun.finditer(value):
            if match.start() >= action.end():
                if match.start() - action.end() <= _FORWARD_GAP:
                    if best < 0 or match.start() < best:
                        best = match.start()
            elif action.start() >= match.end():
                if action.start() - match.end() <= _BACKWARD_GAP:
                    if best < 0 or match.start() < best:
                        best = match.start()
    return best >= 0, best


def requests_pretrial_response(text: str | None) -> bool:
    """Просьба подготовить ОТВЕТ на претензию, а не саму претензию.

    Упоминание «ответа на претензию» внутри фабулы («ответа на претензию не
    поступило») просьбой не является: рядом с ним нет глагола-действия, а если
    он там всё же оказался, побеждает прямая просьба подготовить претензию.
    """
    response_asked, response_at = _requested(text, _RESPONSE_NOUN)
    if not response_asked:
        return False
    pretrial_asked, pretrial_at = _requested(text, _PRETRIAL_NOUN)
    if not pretrial_asked:
        return True
    # Оба совпали. «Ответ на претензию» содержит внутри себя слово «претензию»,
    # поэтому существительное претензии всегда находится правее начала оборота
    # об ответе. Просьба об ответе побеждает только тогда, когда она стоит
    # раньше самостоятельного упоминания претензии.
    return response_at <= pretrial_at


def requests_pretrial(text: str | None) -> bool:
    """Просьба подготовить саму досудебную претензию."""
    pretrial_asked, pretrial_at = _requested(text, _PRETRIAL_NOUN)
    if not pretrial_asked:
        return False
    return not requests_pretrial_response(text)


def resolve_document_type(selected: str | None, text: str | None = None) -> str | None:
    """Итоговый тип документа: выбор пользователя сильнее любого текста.

    ``selected`` — то, что пользователь выбрал явно: кнопка раздела в Telegram
    или карточка документа в Mini App. Пока он есть, разбор текста не
    выполняется вовсе: именно попытка «уточнить» явный выбор по фабуле и
    переворачивала роли сторон.
    """
    chosen = str(selected or "").strip().lower()
    if chosen in DOCUMENT_TYPES:
        return chosen
    if chosen:
        # Непонятный явный выбор — это ошибка вызывающего кода, а не повод
        # угадывать тип по тексту дела.
        return None
    if requests_pretrial_response(text):
        return "pretrial_response"
    if requests_pretrial(text):
        return "pretrial"
    return None


def expected_roles(document_type: str) -> dict[str, str]:
    """Кто отправитель и кто адресат для претензионной пары."""
    return dict(ROLE_MATRIX.get(str(document_type or ""), {}))


def intent_may_switch(data: dict | None, target: str) -> bool:
    """Может ли интент по свободному тексту открыть раздел ``target``.

    Раздел выбирается кнопкой (inline-callback ``doc:<тип>``), и этот выбор
    живёт в состоянии как ``request_kind`` вместе с ``request_id``. Пока такая
    заявка активна, текст дела не вправе перевести её в другой раздел: именно
    так «досудебная претензия» превращалась в «ответ на претензию» — фабула
    претензии почти всегда упоминает и ту и другую.

    Свой же раздел интент открывать вправе: пользователь мог начать заново теми
    же словами, и это не смена типа документа.
    """
    from korgan.request_scope import active_document_kind

    active = active_document_kind(dict(data or {}))
    return active is None or active == str(target or "")
