from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FieldKind(StrEnum):
    TEXT = "text"
    MULTILINE = "multiline"
    IDENTIFIER = "identifier"
    MONEY = "money"
    MONEY_LIST = "money_list"
    PERCENT = "percent"
    INTEGER = "integer"
    DATE = "date"
    BOOL = "bool"
    CHOICE = "choice"


UNKNOWN = "__unknown__"


@dataclass(frozen=True)
class Choice:
    value: str
    label_ru: str
    label_kk: str


@dataclass(frozen=True)
class InterviewField:
    """One deterministic question in the guided fact-collection dialogue.

    ``required`` means the document cannot be drafted until the question is answered. ``unknown_ok``
    means the user may answer "не знаю": that answer is recorded as genuinely undetermined and
    becomes an explicit NEEDS_VERIFICATION item. A required field that is *not* ``unknown_ok`` blocks
    generation instead, because inventing it would be the failure mode this system exists to prevent.
    """

    id: str
    kind: FieldKind
    prompt_ru: str
    prompt_kk: str
    required: bool = False
    unknown_ok: bool = True
    hint_ru: str = ""
    hint_kk: str = ""
    choices: tuple[Choice, ...] = ()
    depends_on: str = ""
    depends_value: str = ""


_REPRESENTATIVE_CHOICES = (
    Choice("director", "Руководитель организации", "Ұйым басшысы"),
    Choice("employee", "Штатный работник", "Штаттық қызметкер"),
    Choice("advocate", "Адвокат", "Адвокат"),
    Choice("legal_consultant", "Юридический консультант", "Заң консультанты"),
    Choice("other", "Иное лицо", "Өзге тұлға"),
)

_FILING_CHOICES = (
    Choice("electronic", "Электронно (судебный кабинет)", "Электронды (сот кабинеті)"),
    Choice("paper", "На бумаге", "Қағаз түрінде"),
)

_YES_NO = (
    Choice("yes", "Да", "Иә"),
    Choice("no", "Нет", "Жоқ"),
)


FIELDS: dict[str, InterviewField] = {
    field.id: field
    for field in (
        InterviewField(
            id="author_name",
            kind=FieldKind.TEXT,
            prompt_ru="Полное наименование (или ФИО) вашей стороны — от чьего имени готовится документ?",
            prompt_kk="Құжат кімнің атынан дайындалады — тараптың толық атауын (немесе Т.А.Ә.) жазыңыз.",
            hint_ru="Например: ТОО «Арман Логистикс».",
            hint_kk="Мысалы: «Арман Логистикс» ЖШС.",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="author_bin",
            kind=FieldKind.IDENTIFIER,
            prompt_ru="БИН/ИИН вашей стороны.",
            prompt_kk="Тараптың БСН/ЖСН нөмірі.",
            hint_ru="12 цифр. Если сейчас нет под рукой — напишите «не знаю».",
            hint_kk="12 сан. Қолжетімсіз болса «білмеймін» деп жазыңыз.",
        ),
        InterviewField(
            id="author_address",
            kind=FieldKind.TEXT,
            prompt_ru="Юридический адрес вашей стороны.",
            prompt_kk="Тараптың заңды мекенжайы.",
        ),
        InterviewField(
            id="opponent_name",
            kind=FieldKind.TEXT,
            prompt_ru="Полное наименование (или ФИО) второй стороны.",
            prompt_kk="Екінші тараптың толық атауы (немесе Т.А.Ә.).",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="opponent_bin",
            kind=FieldKind.IDENTIFIER,
            prompt_ru="БИН/ИИН второй стороны.",
            prompt_kk="Екінші тараптың БСН/ЖСН нөмірі.",
        ),
        InterviewField(
            id="opponent_address",
            kind=FieldKind.TEXT,
            prompt_ru="Адрес второй стороны.",
            prompt_kk="Екінші тараптың мекенжайы.",
        ),
        InterviewField(
            id="basis",
            kind=FieldKind.MULTILINE,
            prompt_ru="Основание требования: вид договора, его номер и дата.",
            prompt_kk="Талап негізі: шарт түрі, нөмірі және күні.",
            hint_ru="Например: договор перевозки № 14 от 12.02.2026.",
            hint_kk="Мысалы: 12.02.2026 ж. № 14 тасымалдау шарты.",
            required=True,
        ),
        InterviewField(
            id="circumstances",
            kind=FieldKind.MULTILINE,
            prompt_ru="Опишите обстоятельства: что вы исполнили, что не исполнила вторая сторона.",
            prompt_kk="Мән-жайларды сипаттаңыз: сіз нені орындадыңыз, екінші тарап нені орындамады.",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="contract_amount",
            kind=FieldKind.MONEY,
            prompt_ru="Общая сумма по договору/актам в тенге.",
            prompt_kk="Шарт/актілер бойынша жалпы сома (теңге).",
            hint_ru="Только число, например 3600000.",
            hint_kk="Тек сан, мысалы 3600000.",
        ),
        InterviewField(
            id="payments",
            kind=FieldKind.MONEY_LIST,
            prompt_ru="Какие оплаты уже поступили? Укажите каждую суммой и датой.",
            prompt_kk="Қандай төлемдер түсті? Әрқайсысын сомасымен және күнімен көрсетіңіз.",
            hint_ru="Формат: 1200000 от 15.03.2026; 600000 от 02.05.2026. Если оплат не было — «нет».",
            hint_kk="Пішімі: 15.03.2026 ж. 1200000; 02.05.2026 ж. 600000. Төлем болмаса — «жоқ».",
        ),
        InterviewField(
            id="obligation_due_date",
            kind=FieldKind.DATE,
            prompt_ru="Точная дата, когда обязательство должно было быть исполнено.",
            prompt_kk="Міндеттеме орындалуға тиіс болған нақты күн.",
            hint_ru="Формат ДД.ММ.ГГГГ. От неё считаются неустойка и сроки.",
            hint_kk="Пішімі КК.АА.ЖЖЖЖ. Осы күннен тұрақсыздық айыбы мен мерзімдер есептеледі.",
            required=True,
        ),
        InterviewField(
            id="penalty_rate",
            kind=FieldKind.PERCENT,
            prompt_ru="Ставка договорной неустойки в процентах за день просрочки.",
            prompt_kk="Шарттық тұрақсыздық айыбының мөлшерлемесі (күніне пайызбен).",
            hint_ru="Например 0.1. Если неустойка договором не установлена — «нет».",
            hint_kk="Мысалы 0.1. Шартта белгіленбесе — «жоқ».",
        ),
        InterviewField(
            id="penalty_cap",
            kind=FieldKind.PERCENT,
            prompt_ru="Предельный размер неустойки в процентах от суммы долга, если он есть в договоре.",
            prompt_kk="Шартта болса, борыш сомасынан тұрақсыздық айыбының шекті мөлшері (пайызбен).",
            hint_ru="Например 10. Если ограничения нет — «нет».",
            hint_kk="Мысалы 10. Шектеу болмаса — «жоқ».",
        ),
        InterviewField(
            id="other_amount",
            kind=FieldKind.MONEY,
            prompt_ru="Иные суммы, которые вы требуете сверх долга и неустойки.",
            prompt_kk="Борыш пен тұрақсыздық айыбынан тыс талап ететін өзге сомалар.",
            hint_ru="Убытки, расходы. Не повторяйте здесь сумму договора. Если нет — «нет».",
            hint_kk="Залал, шығыс. Шарт сомасын қайталамаңыз. Болмаса — «жоқ».",
        ),
        InterviewField(
            id="pretrial_required",
            kind=FieldKind.CHOICE,
            prompt_ru="Договор устанавливает обязательный претензионный (досудебный) порядок?",
            prompt_kk="Шартта міндетті наразылық (сотқа дейінгі) тәртіп белгіленген бе?",
            choices=_YES_NO,
            required=True,
        ),
        InterviewField(
            id="pretrial_sent_date",
            kind=FieldKind.DATE,
            prompt_ru="Дата направления претензии второй стороне.",
            prompt_kk="Наразылық екінші тарапқа жіберілген күн.",
            depends_on="pretrial_required",
            depends_value="yes",
        ),
        InterviewField(
            id="representative_kind",
            kind=FieldKind.CHOICE,
            prompt_ru="Кто подписывает документ?",
            prompt_kk="Құжатқа кім қол қояды?",
            choices=_REPRESENTATIVE_CHOICES,
            required=True,
        ),
        InterviewField(
            id="representative_name",
            kind=FieldKind.TEXT,
            prompt_ru="ФИО подписанта.",
            prompt_kk="Қол қоюшының Т.А.Ә.",
            required=True,
        ),
        InterviewField(
            id="representative_can_sign",
            kind=FieldKind.CHOICE,
            prompt_ru="В доверенности прямо указано право подписывать и подавать иск?",
            prompt_kk="Сенімхатта талап арызға қол қою және беру құқығы тікелей көрсетілген бе?",
            choices=_YES_NO,
            depends_on="representative_kind",
            depends_value="!director",
        ),
        InterviewField(
            id="filing_mode",
            kind=FieldKind.CHOICE,
            prompt_ru="Как планируете подавать документ?",
            prompt_kk="Құжатты қалай беруді жоспарлайсыз?",
            choices=_FILING_CHOICES,
            required=True,
        ),
        InterviewField(
            id="copies_prepared",
            kind=FieldKind.CHOICE,
            prompt_ru="Копии документа и приложений по числу участников подготовлены?",
            prompt_kk="Қатысушылар санына сай құжат пен қосымшалардың көшірмелері дайын ба?",
            choices=_YES_NO,
            depends_on="filing_mode",
            depends_value="paper",
        ),
        InterviewField(
            id="evidence_list",
            kind=FieldKind.MULTILINE,
            prompt_ru="Перечислите документы, которые у вас есть на руках.",
            prompt_kk="Қолыңызда бар құжаттарды тізіңіз.",
            hint_ru="Например: договор, акт оказанных услуг, счёт-фактура, претензия, чек об отправке, "
            "квитанция госпошлины, справка о регистрации.",
            hint_kk="Мысалы: шарт, көрсетілген қызмет актісі, шот-фактура, наразылық, жіберу түбіртегі, "
            "мемлекеттік баж түбіртегі, тіркеу анықтамасы.",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="case_number",
            kind=FieldKind.TEXT,
            prompt_ru="Номер дела и наименование суда, в производстве которого оно находится.",
            prompt_kk="Іс нөмірі және оны қарап жатқан соттың атауы.",
            required=True,
        ),
        InterviewField(
            id="contested_act",
            kind=FieldKind.MULTILINE,
            prompt_ru="Какой акт, решение или действие вы обжалуете? Укажите орган, номер и дату.",
            prompt_kk="Қандай акт, шешім немесе әрекетке шағымданасыз? Органды, нөмірді және күнді көрсетіңіз.",
            required=True,
        ),
        InterviewField(
            id="motion_request",
            kind=FieldKind.MULTILINE,
            prompt_ru="О чём вы просите суд в этом ходатайстве?",
            prompt_kk="Осы өтінішхатта соттан не сұрайсыз?",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="response_position",
            kind=FieldKind.MULTILINE,
            prompt_ru="С чем именно в иске вы не согласны и почему?",
            prompt_kk="Талап арыздың нақты қай тұсымен келіспейсіз және неге?",
            required=True,
            unknown_ok=False,
        ),
        InterviewField(
            id="demand_deadline_days",
            kind=FieldKind.INTEGER,
            prompt_ru="Сколько календарных дней вы даёте на добровольное погашение?",
            prompt_kk="Ерікті түрде өтеуге қанша күнтізбелік күн бересіз?",
            hint_ru="Обычно берётся срок из договора. Если в договоре не указан — «не знаю».",
            hint_kk="Әдетте шарттағы мерзім алынады. Шартта болмаса — «білмеймін».",
        ),
        InterviewField(
            id="contract_subject",
            kind=FieldKind.MULTILINE,
            prompt_ru="Предмет договора: что именно одна сторона обязуется сделать для другой.",
            prompt_kk="Шарт мәні: бір тарап екіншісі үшін нақты нені орындауға міндеттенеді.",
            required=True,
            unknown_ok=False,
        ),
    )
}


def field_by_id(field_id: str) -> InterviewField:
    try:
        return FIELDS[field_id]
    except KeyError as error:
        raise KeyError(f"Unknown interview field: {field_id}") from error
