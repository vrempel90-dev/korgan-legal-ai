"""Контракт единственного числового источника иска.

Зачем модуль существует
-----------------------
Числа искового заявления — цена иска, госпошлина, основной долг, неустойка,
итог ко взысканию — до сих пор рождались в двух местах одновременно. Модель
писала их прозой в просительную часть, а код разбирал эту прозу обратно в
числа: ``late_interest_hotfix._property_components`` для цены иска и
``claim_money_ledger`` для повторного её пересчёта в финалайзере. Два разных
обхода одного текста означают ровно то, что и должны означать: рано или поздно
они расходятся, и документ начинает утверждать две разные суммы.

Здесь описан один результат расчёта, из которого берутся все числовые поля
документа. Модуль ничего не считает и ничего не парсит: он задаёт форму, в
которой расчёт передаётся дальше, и словарь подстановок для post-processing.

Почему ``INSUFFICIENT_DATA`` — статус, а не текст
------------------------------------------------
«Требует проверки» внутри судебного текста читается ответчиком и судьёй как
часть требования истца. Недостаток данных — это состояние поля расчёта, а не
фраза: поле остаётся незаполненным, а причина уходит юристу отдельным
сообщением. Строка, которую написала бы модель, объясняя пропуск, здесь
невозможна по устройству типа.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from korgan.legal_calc import format_kzt


class FieldStatus(StrEnum):
    """Состояние одного числового поля расчёта."""

    #: Значение выведено детерминированно из подтверждённых входных данных.
    CALCULATED = "calculated"
    #: Подтверждённых входных данных не хватает. Значения нет и не будет
    #: угадано; ``missing`` называет, чего именно недостаёт.
    INSUFFICIENT_DATA = "insufficient_data"
    #: Поле к этому делу не относится (например, неустойка не заявлена).
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class CalculationField:
    """Одно числовое поле: значение, его основание и разбор.

    ``source`` — не ссылка на норму, а описание входных данных, из которых
    получено значение: «стоимость поставки 8 750 000 ₸ минус платёж
    07.04.2026». Именно эту строку юрист сверяет с материалами дела, поэтому
    она обязана называть исходники, а не пересказывать результат.
    """

    key: str
    status: FieldStatus
    value: int | None = None
    source: str = ""
    breakdown: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is FieldStatus.CALCULATED and self.value is None:
            raise ValueError(f"Поле {self.key} объявлено рассчитанным без значения")
        if self.status is not FieldStatus.CALCULATED and self.value is not None:
            raise ValueError(f"Поле {self.key} не рассчитано, но несёт значение")
        if self.status is FieldStatus.INSUFFICIENT_DATA and not self.missing:
            raise ValueError(f"Поле {self.key} без данных, но не сказано, каких именно")

    @property
    def ready(self) -> bool:
        return self.status is FieldStatus.CALCULATED

    @property
    def display(self) -> str:
        """Сумма в том виде, в каком она печатается в документе."""
        return format_kzt(self.value) if self.value is not None else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "value": self.value,
            "source": self.source,
            "breakdown": list(self.breakdown),
            "missing": list(self.missing),
        }


def calculated(key: str, value: int, *, source: str, breakdown: tuple[str, ...] = ()) -> CalculationField:
    return CalculationField(
        key=key, status=FieldStatus.CALCULATED, value=int(value), source=source, breakdown=breakdown
    )


def insufficient(key: str, *missing: str, source: str = "") -> CalculationField:
    return CalculationField(
        key=key, status=FieldStatus.INSUFFICIENT_DATA, source=source, missing=tuple(missing)
    )


def not_applicable(key: str, *, source: str = "") -> CalculationField:
    return CalculationField(key=key, status=FieldStatus.NOT_APPLICABLE, source=source)


#: Плейсхолдеры, которыми модель обязана обозначать денежные суммы. Значения
#: подставляет post-processing; собственное число модели в эти поля не
#: попадает даже тогда, когда она его написала.
PRINCIPAL_TOKEN = "{{principal_amount}}"
PENALTY_TOKEN = "{{penalty_amount}}"
CLAIM_PRICE_TOKEN = "{{claim_price}}"
STATE_DUTY_TOKEN = "{{state_duty}}"
TOTAL_CLAIM_TOKEN = "{{total_claim}}"


@dataclass(frozen=True, slots=True)
class ClaimCalculation:
    """Единственный числовой результат по денежным требованиям иска.

    Цена иска здесь — сумма имущественных требований без судебных расходов, а
    ``total_claim`` — то, что фактически просят взыскать с ответчика, то есть
    цена иска плюс возмещаемая госпошлина. Две величины разведены намеренно:
    от первой считается пошлина, вторую читает клиент, и подмена одной другой
    даёт ошибку ровно в размере пошлины.
    """

    principal: CalculationField
    penalty: CalculationField
    claim_price: CalculationField
    state_duty: CalculationField
    total_claim: CalculationField
    #: Прочие имущественные требования, вошедшие в цену иска.
    other_components: tuple[tuple[str, int], ...] = ()
    #: Сообщения юристу. В судебный текст не попадают никогда.
    lawyer_notes: tuple[str, ...] = ()
    #: Слепок входных данных расчёта — для release-проверок и разбора инцидентов.
    inputs: dict[str, Any] = field(default_factory=dict)

    def fields(self) -> tuple[CalculationField, ...]:
        return (self.principal, self.penalty, self.claim_price, self.state_duty, self.total_claim)

    @property
    def ready(self) -> bool:
        """Готов ли расчёт к печати в документе.

        Неустойка со статусом ``NOT_APPLICABLE`` готовности не мешает: иск без
        требования о неустойке — обычный иск, а не иск с пробелом.
        """
        return all(
            item.status is not FieldStatus.INSUFFICIENT_DATA for item in self.fields()
        ) and self.claim_price.ready

    def insufficient_fields(self) -> tuple[CalculationField, ...]:
        return tuple(item for item in self.fields() if item.status is FieldStatus.INSUFFICIENT_DATA)

    def placeholders(self) -> dict[str, str]:
        """Подстановки для post-processing.

        Поле без значения подстановки не получает: незаполненный плейсхолдер
        обязан остаться видимым дефектом, а не превратиться в пустое место
        посреди процессуальной фразы.
        """
        mapping = {
            PRINCIPAL_TOKEN: self.principal,
            PENALTY_TOKEN: self.penalty,
            CLAIM_PRICE_TOKEN: self.claim_price,
            STATE_DUTY_TOKEN: self.state_duty,
            TOTAL_CLAIM_TOKEN: self.total_claim,
        }
        return {token: item.display for token, item in mapping.items() if item.ready}

    def as_dict(self) -> dict[str, Any]:
        return {
            "principal": self.principal.as_dict(),
            "penalty": self.penalty.as_dict(),
            "claim_price": self.claim_price.as_dict(),
            "state_duty": self.state_duty.as_dict(),
            "total_claim": self.total_claim.as_dict(),
            "other_components": [{"label": label, "amount": amount} for label, amount in self.other_components],
            "lawyer_notes": list(self.lawyer_notes),
            "inputs": dict(self.inputs),
            "ready": self.ready,
        }
