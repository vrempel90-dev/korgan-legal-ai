from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from korgan_legal_ai.blueprints.registry import (
    CLAIM_DEBT_RECOVERY,
    COMPLAINT,
    PRETRIAL_DEMAND,
    RESPONSE,
)


@dataclass(frozen=True)
class EvalCase:
    """One synthetic matter with its independently derived expectations.

    Parties and figures are invented. Nothing here comes from the private reference corpus, so a
    failing assertion can print the whole case without exposing a real client.

    ``expected_*`` values are worked out by hand from ``formula`` and compared against the
    calculation layer. The point is to catch the layer agreeing with itself: the expectation is
    written independently of the code that produces the number.
    """

    id: str
    title: str
    blueprint_key: str
    answers: dict[str, str]
    as_of: date
    formula: str
    expected_principal: Decimal | None = None
    expected_penalty: Decimal | None = None
    expected_total: Decimal | None = None
    # Phrases that would mean the document declared a supplied fact to be missing. A false
    # NEEDS_VERIFICATION on determined data is treated as a defect, not as harmless caution.
    must_not_say: tuple[str, ...] = ()
    # Phrases that must be present because the datum genuinely was not supplied.
    must_say: tuple[str, ...] = ()
    # Verification items the case must produce, because the underlying question is genuinely open.
    expected_needs: tuple[str, ...] = ()
    # House-style rules that cannot apply to this case, with the reason. Used only where the
    # missing layout is the correct outcome — never to hide a drafting gap.
    style_exempt: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


_COURT_TAIL = {
    "representative_kind": "Руководитель организации",
    "representative_name": "Асанов А.А.",
    "filing_mode": "Электронно (судебный кабинет)",
}

_FULL_ATTACHMENTS = (
    "договор, акт оказанных услуг, счёт-фактура, претензия, чек об отправке претензии, "
    "квитанция об уплате госпошлины, справка о регистрации, приказ о назначении руководителя"
)

_SUPPLIED_PROBES = (
    "Нужен явно подтвержденный срок исполнения обязательства",
    "Не указан подписант",
    "Не выбран способ подачи",
    "Не установлено, содержит ли договор обязательный досудебный порядок",
)


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="E1_partial_payment",
        title="Перевозка: частичная оплата, договорная неустойка",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Арман Логистикс»",
            "author_bin": "180340012345",
            "author_address": "г. Астана, ул. Кабанбай батыра, 12",
            "opponent_name": "ТОО «Нова Трейд»",
            "opponent_bin": "200140098765",
            "opponent_address": "г. Алматы, пр. Достык, 44",
            "basis": "договор перевозки № 14 от 12.02.2026",
            "circumstances": "Перевозка выполнена в полном объёме; акт подписан без замечаний; "
            "оплата в установленный срок не поступила",
            "contract_amount": "3600000",
            "payments": "1200000 от 15.03.2026",
            "obligation_due_date": "03.06.2026",
            "penalty_rate": "0.1",
            "penalty_cap": "10",
            "other_amount": "нет",
            "pretrial_required": "да",
            "pretrial_sent_date": "20.06.2026",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 3 600 000 − 1 200 000 = 2 400 000; "
            "просрочка 03.06.2026→15.08.2026 = 73 дн.; "
            "неустойка = 2 400 000 × 0,1% × 73 = 175 200 (потолок 10% = 240 000, не достигнут); "
            "итого = 2 400 000 + 175 200 = 2 575 200"
        ),
        expected_principal=Decimal("2400000"),
        expected_penalty=Decimal("175200.00"),
        expected_total=Decimal("2575200.00"),
        must_not_say=_SUPPLIED_PROBES,
        tags=("money", "partial_payment", "penalty"),
    ),
    EvalCase(
        id="E2_multiple_payments",
        title="Поставка: несколько частичных оплат, неустойка по убывающему остатку",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Сапа Строй»",
            "author_bin": "150240054321",
            "author_address": "г. Шымкент, ул. Тауке хана, 5",
            "opponent_name": "ТОО «Мега Ритейл»",
            "opponent_bin": "210340011122",
            "opponent_address": "г. Караганда, ул. Ерубаева, 31",
            "basis": "договор поставки № 88 от 20.01.2026",
            "circumstances": "Товар поставлен тремя партиями; накладные подписаны; "
            "оплата произведена частично",
            "contract_amount": "9000000",
            "payments": "3000000 от 10.04.2026; 2000000 от 20.06.2026",
            "obligation_due_date": "01.03.2026",
            "penalty_rate": "0.1",
            "penalty_cap": "нет",
            "other_amount": "нет",
            "pretrial_required": "да",
            "pretrial_sent_date": "01.07.2026",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 9 000 000 − 3 000 000 − 2 000 000 = 4 000 000; "
            "01.03→10.04 = 40 дн. на 9 000 000 → 360 000; "
            "10.04→20.06 = 71 дн. на 6 000 000 → 426 000; "
            "20.06→15.08 = 56 дн. на 4 000 000 → 224 000; "
            "неустойка = 1 010 000; итого = 4 000 000 + 1 010 000 = 5 010 000"
        ),
        expected_principal=Decimal("4000000"),
        expected_penalty=Decimal("1010000.00"),
        expected_total=Decimal("5010000.00"),
        must_not_say=_SUPPLIED_PROBES,
        tags=("money", "partial_payment", "penalty", "trap"),
    ),
    EvalCase(
        id="E3_repaid_penalty_only",
        title="Долг погашен полностью: остаётся только неустойка за период просрочки",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Астана Сервис»",
            "author_bin": "160140077788",
            "author_address": "г. Астана, ул. Сыганак, 10",
            "opponent_name": "ТОО «Батыс Групп»",
            "opponent_bin": "190240033344",
            "opponent_address": "г. Актобе, ул. Абилкайыр хана, 2",
            "basis": "договор подряда № 3 от 15.01.2026",
            "circumstances": "Работы выполнены и приняты; оплата произведена с просрочкой",
            "contract_amount": "5000000",
            "payments": "5000000 от 01.05.2026",
            "obligation_due_date": "01.03.2026",
            "penalty_rate": "0.1",
            "penalty_cap": "нет",
            "other_amount": "нет",
            "pretrial_required": "да",
            "pretrial_sent_date": "10.05.2026",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 5 000 000 − 5 000 000 = 0; "
            "просрочка 01.03.2026→01.05.2026 = 61 дн. на остаток 5 000 000; "
            "неустойка = 5 000 000 × 0,1% × 61 = 305 000; "
            "после 01.05 остаток 0, начисление прекращается; итого = 305 000"
        ),
        expected_principal=Decimal("0"),
        expected_penalty=Decimal("305000.00"),
        expected_total=Decimal("305000.00"),
        must_not_say=_SUPPLIED_PROBES,
        tags=("money", "trap", "penalty"),
    ),
    EvalCase(
        id="E4_other_amount_echo",
        title="«Иные суммы» повторяют уже учтённый долг",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Алтын Дән»",
            "author_bin": "170140099001",
            "author_address": "г. Костанай, ул. Байтурсынова, 7",
            "opponent_name": "ТОО «Восток Агро»",
            "opponent_bin": "200240088776",
            "opponent_address": "г. Павлодар, ул. Торайгырова, 19",
            "basis": "договор поставки зерна № 21 от 05.02.2026",
            "circumstances": "Зерно поставлено; накладная подписана; оплата поступила частично",
            "contract_amount": "4000000",
            "payments": "1000000",
            "obligation_due_date": "01.06.2026",
            "penalty_rate": "нет",
            "penalty_cap": "нет",
            # The user repeats the outstanding balance in the catch-all field. It must be excluded
            # and flagged, never added on top of the debt it already is.
            "other_amount": "3000000",
            "pretrial_required": "да",
            "pretrial_sent_date": "15.06.2026",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 4 000 000 − 1 000 000 = 3 000 000; "
            "«иные суммы» 3 000 000 повторяют остаток долга и исключаются; "
            "итого = 3 000 000, а не 6 000 000"
        ),
        expected_principal=Decimal("3000000"),
        expected_penalty=Decimal("0"),
        expected_total=Decimal("3000000"),
        must_not_say=_SUPPLIED_PROBES,
        tags=("money", "trap", "double_counting"),
    ),
    EvalCase(
        id="E5_penalty_cap",
        title="Договорный потолок неустойки ограничивает начисление",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Темир Транс»",
            "author_bin": "140140055667",
            "author_address": "г. Атырау, ул. Азаттык, 40",
            "opponent_name": "ТОО «Каспий Ойл Сервис»",
            "opponent_bin": "180240044556",
            "opponent_address": "г. Актау, 12 мкр, д. 3",
            "basis": "договор оказания услуг № 9 от 10.01.2026",
            "circumstances": "Услуги оказаны и приняты; оплата не поступила",
            "contract_amount": "2000000",
            "payments": "нет",
            "obligation_due_date": "01.02.2026",
            "penalty_rate": "0.5",
            "penalty_cap": "10",
            "other_amount": "нет",
            "pretrial_required": "нет",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 2 000 000; просрочка 01.02.2026→15.08.2026 = 195 дн.; "
            "без потолка 2 000 000 × 0,5% × 195 = 1 950 000; "
            "потолок 10% от 2 000 000 = 200 000 → применяется; "
            "итого = 2 000 000 + 200 000 = 2 200 000"
        ),
        expected_principal=Decimal("2000000"),
        expected_penalty=Decimal("200000.00"),
        expected_total=Decimal("2200000.00"),
        must_not_say=("Нужен явно подтвержденный срок исполнения обязательства", "Не указан подписант"),
        tags=("money", "penalty", "cap"),
    ),
    EvalCase(
        id="E6_pretrial_demand",
        title="Досудебная претензия: денежное требование вне суда",
        blueprint_key=PRETRIAL_DEMAND.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Жетысу Пром»",
            "author_bin": "130140022233",
            "author_address": "г. Талдыкорган, ул. Абая, 55",
            "opponent_name": "ТОО «Синегорье»",
            "opponent_bin": "210140066778",
            "opponent_address": "г. Усть-Каменогорск, ул. Кабанбай батыра, 148",
            "basis": "договор аренды оборудования № 5 от 01.03.2026",
            "circumstances": "Оборудование передано по акту; арендная плата не внесена",
            "contract_amount": "1800000",
            "payments": "нет",
            "obligation_due_date": "01.07.2026",
            "penalty_rate": "нет",
            "penalty_cap": "нет",
            "other_amount": "нет",
            "demand_deadline_days": "10",
            "representative_kind": "Руководитель организации",
            "representative_name": "Сериков С.С.",
            "evidence_list": "договор аренды, акт приёма-передачи оборудования, счёт на оплату",
        },
        formula="долг = 1 800 000, оплат нет, неустойка договором не установлена; итого = 1 800 000",
        expected_principal=Decimal("1800000"),
        expected_penalty=Decimal("0"),
        expected_total=Decimal("1800000"),
        must_not_say=("Нужен явно подтвержденный срок исполнения обязательства", "Не указан подписант"),
        notes="Претензия адресуется контрагенту, а не суду: подсудность и госпошлина не применяются.",
        tags=("money", "non_court"),
    ),
    EvalCase(
        id="E7_response_no_money",
        title="Отзыв на иск: документ без денежного расчёта",
        blueprint_key=RESPONSE.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Ново Пак»",
            "author_bin": "190140011223",
            "author_address": "г. Алматы, ул. Розыбакиева, 200",
            "opponent_name": "ТОО «Гранд Импорт»",
            "opponent_address": "г. Алматы, пр. Аль-Фараби, 77",
            "case_number": "2-4521/2026, СМЭС города Алматы",
            "basis": "договор поставки № 31 от 09.02.2026",
            "circumstances": "Товар получен не в полном объёме; расхождение зафиксировано актом",
            "response_position": "Требования не признаю в части непоставленного товара; "
            "расчёт истца не учитывает возврат части партии",
            "representative_kind": "Адвокат",
            "representative_name": "Ким В.П.",
            "representative_can_sign": "да",
            "filing_mode": "Электронно (судебный кабинет)",
            "evidence_list": "договор поставки, акт о расхождении, доверенность, "
            "удостоверение адвоката",
        },
        formula="денежных требований документ не заявляет; расчёт не производится",
        expected_principal=None,
        expected_penalty=None,
        expected_total=None,
        must_not_say=("ЦЕНА ИСКА", "Государственная пошлина", "Не указан подписант"),
        tags=("no_money",),
    ),
    EvalCase(
        id="E8_complaint_no_money",
        title="Жалоба на решение органа: обжалование без денежного требования",
        blueprint_key=COMPLAINT.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Эко Ресурс»",
            "author_bin": "200140044332",
            "author_address": "г. Астана, ул. Туран, 18",
            "opponent_name": "Департамент экологии по городу Астане",
            "opponent_address": "г. Астана, ул. Бейбитшилик, 11",
            "contested_act": "предписание № 77 от 03.07.2026 об устранении нарушений",
            "circumstances": "Предписание вынесено без осмотра объекта; "
            "нарушение зафиксировано по устаревшим данным",
            "obligation_due_date": "03.07.2026",
            "representative_kind": "Руководитель организации",
            "representative_name": "Нурланов Н.Н.",
            "filing_mode": "На бумаге",
            "evidence_list": "копия предписания, письмо о проведённой модернизации, "
            "приказ о назначении руководителя",
        },
        formula="денежных требований документ не заявляет; расчёт не производится",
        expected_principal=None,
        expected_penalty=None,
        expected_total=None,
        must_not_say=("ЦЕНА ИСКА", "Государственная пошлина", "Не указан подписант"),
        tags=("no_money",),
    ),
)


# Cases used for acceptance rather than regression: they are deliberately outside the eval suite so
# that "the suite passes" and "new matters work" stay separate statements.
ACCEPTANCE_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="A1_construction_penalty",
        title="Приёмка: подряд с неустойкой и частичной оплатой",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Курылыс Мастер»",
            "author_bin": "120140077665",
            "author_address": "г. Актобе, ул. Санкибай батыра, 14",
            "opponent_name": "ТОО «Дала Инвест»",
            "opponent_bin": "220140099887",
            "opponent_address": "г. Уральск, ул. Достык, 210",
            "basis": "договор подряда № 47 от 03.03.2026",
            "circumstances": "Работы выполнены и приняты по акту от 10.05.2026; "
            "заказчик оплатил часть стоимости; остаток не погашен",
            "contract_amount": "12500000",
            "payments": "4500000 от 25.05.2026",
            "obligation_due_date": "20.05.2026",
            "penalty_rate": "0.2",
            "penalty_cap": "15",
            "other_amount": "нет",
            "pretrial_required": "да",
            "pretrial_sent_date": "05.06.2026",
            "evidence_list": _FULL_ATTACHMENTS,
            **_COURT_TAIL,
        },
        formula=(
            "долг = 12 500 000 − 4 500 000 = 8 000 000; "
            "20.05→25.05 = 5 дн. на остаток 12 500 000 → 12 500 000 × 0,2% × 5 = 125 000; "
            "25.05→15.08 = 82 дн. на остаток 8 000 000 → 8 000 000 × 0,2% × 82 = 1 312 000; "
            "неустойка = 125 000 + 1 312 000 = 1 437 000; "
            "потолок 15% считается от долга на дату просрочки: 12 500 000 × 15% = 1 875 000 — "
            "не достигнут; итого = 8 000 000 + 1 437 000 = 9 437 000"
        ),
        expected_principal=Decimal("8000000"),
        expected_penalty=Decimal("1437000.00"),
        expected_total=Decimal("9437000.00"),
        # Read against the remaining balance the ceiling would be 1 200 000 and would bind. The
        # wording decides which reading applies, so the case must surface the question.
        expected_needs=("penalty_cap_base",),
        must_not_say=_SUPPLIED_PROBES,
        tags=("acceptance", "money", "penalty", "partial_payment"),
    ),
    EvalCase(
        id="A2_appeal_against_act",
        title="Приёмка: обжалование акта без денежного расчёта",
        blueprint_key=COMPLAINT.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Агро Стандарт»",
            "author_bin": "210240011009",
            "author_address": "г. Тараз, ул. Толе би, 62",
            "opponent_name": "Управление земельных отношений по Жамбылской области",
            "opponent_address": "г. Тараз, пл. Достык, 1",
            "contested_act": "решение № 214 от 12.06.2026 об отказе в продлении права землепользования",
            "circumstances": "Заявление подано в срок; отказ мотивирован отсутствием документа, "
            "который был представлен вместе с заявлением",
            "obligation_due_date": "12.06.2026",
            "representative_kind": "Юридический консультант",
            "representative_name": "Оспанов Б.К.",
            "representative_can_sign": "да",
            "filing_mode": "Электронно (судебный кабинет)",
            "evidence_list": "копия решения, опись поданных документов, доверенность, "
            "свидетельство юридического консультанта",
        },
        formula="денежных требований нет; расчёт не производится",
        must_not_say=("ЦЕНА ИСКА", "Государственная пошлина", "Не указан подписант"),
        tags=("acceptance", "no_money"),
    ),
    EvalCase(
        id="A3_setoff_partial_payments",
        title="Приёмка: зачёт и несколько частичных оплат",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Аква Лайн»",
            "author_bin": "110140033221",
            "author_address": "г. Семей, ул. Шакарима, 90",
            "opponent_name": "ТОО «Ирбис Логистик»",
            "opponent_bin": "230140055443",
            "opponent_address": "г. Петропавловск, ул. Конституции, 25",
            "basis": "договор оказания услуг № 62 от 15.01.2026",
            "circumstances": "Услуги оказаны; часть оплачена платежами; часть погашена зачётом "
            "встречного требования по акту зачёта",
            "contract_amount": "7200000",
            "payments": "1200000 от 01.04.2026; 800000 от 15.05.2026; 1000000 от 01.07.2026",
            "obligation_due_date": "01.04.2026",
            "penalty_rate": "нет",
            "penalty_cap": "нет",
            "other_amount": "нет",
            "pretrial_required": "да",
            "pretrial_sent_date": "10.07.2026",
            "evidence_list": "договор, акт оказанных услуг, акт сверки, платёжные поручения, "
            "претензия, чек об отправке претензии, квитанция об уплате госпошлины, "
            "справка о регистрации, приказ о назначении руководителя",
            **_COURT_TAIL,
        },
        formula=(
            "долг = 7 200 000 − 1 200 000 − 800 000 − 1 000 000 = 4 200 000; "
            "неустойка договором не установлена → 0; итого = 4 200 000"
        ),
        expected_principal=Decimal("4200000"),
        expected_penalty=Decimal("0"),
        expected_total=Decimal("4200000"),
        must_not_say=_SUPPLIED_PROBES,
        tags=("acceptance", "money", "partial_payment"),
    ),
    EvalCase(
        id="A4_missing_data_discipline",
        title="Приёмка: намеренно неполные данные — проверка дисциплины NEEDS_VERIFICATION",
        blueprint_key=CLAIM_DEBT_RECOVERY.key,
        as_of=date(2026, 8, 15),
        answers={
            "author_name": "ТОО «Бота Трейд»",
            "author_bin": "не знаю",
            "author_address": "не знаю",
            "opponent_name": "ТОО «Север Снаб»",
            "opponent_bin": "не знаю",
            "opponent_address": "не знаю",
            "basis": "договор поставки без номера",
            "circumstances": "Товар поставлен; оплата не поступила",
            "contract_amount": "1500000",
            "payments": "нет",
            "obligation_due_date": "01.06.2026",
            "penalty_rate": "нет",
            "penalty_cap": "нет",
            "other_amount": "нет",
            # Deliberately undetermined: signatory, filing route and pretrial requirement.
            "pretrial_required": "не знаю",
            "representative_kind": "не знаю",
            "representative_name": "не знаю",
            "filing_mode": "не знаю",
            "evidence_list": "договор, накладная",
        },
        formula="долг = 1 500 000, оплат нет, неустойки нет; итого = 1 500 000",
        expected_principal=Decimal("1500000"),
        expected_penalty=Decimal("0"),
        expected_total=Decimal("1500000"),
        must_say=(
            "NEEDS_VERIFICATION",
            "Не указан подписант",
            "Не выбран способ подачи",
        ),
        # The amount and the due date were supplied, so they must not be reported as unknown.
        must_not_say=("Нужен явно подтвержденный срок исполнения обязательства",),
        style_exempt={
            "signature.representative_ecp": "Подписант намеренно не указан, поэтому блок подписи "
            "не может быть построен — отсутствие блока здесь и есть правильный результат.",
        },
        notes="Проверяет, что система не выдумывает подсудность, пошлину и подписанта.",
        tags=("acceptance", "needs_verification"),
    ),
)


ALL_CASES: tuple[EvalCase, ...] = EVAL_CASES + ACCEPTANCE_CASES
