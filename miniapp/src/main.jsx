import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home,
  UserRound, ArrowRight, ArrowLeft, Search, ChevronRight, CheckCircle2,
  ScrollText, Reply, Send, Download, LockKeyhole, Sparkles, Trash2,
  Languages, AlertTriangle, Paperclip, FileSignature, Headphones, CircleHelp,
  RefreshCw, ExternalLink, CreditCard, BadgeCheck, Clock3, WifiOff, Link2,
  LoaderCircle, ShieldAlert, Banknote, ClipboardCheck, XCircle
} from 'lucide-react';
import './styles.css';
import { isBackendConnected, korganApi } from './korganApi';
import {
  loadState, saveDraft, setLanguage as persistLanguage,
  clearLocalCaseData, clearAllLocalData
} from './store';
import { getTelegramUser, getTelegramWebApp, initTelegram, haptic } from './telegram';
import { PERSONAL_LAWYER_URL, personalLawyerCopy } from './personalLawyer';
import { deliverDocument, openSignedDocument } from './documentDelivery';
import { requireDocumentPayment, startDocumentPaymentPolling } from './documentPaymentPolling';
import { interpretGeneration, startGenerationPolling } from './generationJob';
import { createBootstrapSession } from './bootstrapSession';
import { resolveScreen } from './screenState';
import { createLatestAction } from './latestAction';
import { pollingNoticeUpdate } from './pollingNotice';
import { clientMessage as messageForClient } from './clientMessage';

const TERMS_VERSION = '2026-08-16-v1';
const WHATSAPP_URL = 'https://wa.me/77005000553';
const SUPPORT_WHATSAPP_URL = 'https://wa.me/77712841932';

const DOCUMENTS = [
  { id: 'claim', ru: ['Исковое заявление', 'Подготовка иска в суд'], kk: ['Талап қою арызы', 'Сотқа талап қою құжаты'], icon: Scale },
  { id: 'contract', ru: ['Договор', 'Профессиональный проект договора'], kk: ['Шарт', 'Кәсіби шарт жобасы'], icon: FileSignature },
  { id: 'response', ru: ['Отзыв на иск', 'Позиция и возражения ответчика'], kk: ['Талапқа пікір', 'Жауапкердің ұстанымы мен қарсылықтары'], icon: Reply },
  { id: 'pretrial', ru: ['Досудебная претензия', 'Требование до обращения в суд'], kk: ['Сотқа дейінгі талап', 'Сотқа жүгінгенге дейінгі талап'], icon: ScrollText },
  { id: 'pretrial_response', ru: ['Ответ на претензию', 'Позиция получателя претензии'], kk: ['Сотқа дейінгі талапқа жауап', 'Талап алушының ұстанымы'], icon: FileText },
];

const L = {
  ru: {
    home: 'Главная', cases: 'Дела', lawyer: 'AI-юрист', profile: 'Профиль', help: 'Помощь',
    consentTitle: 'Условия использования KORGAN Legal AI',
    consentText: 'KORGAN — система искусственного интеллекта для права Республики Казахстан. Ответы и документы формируются по данным пользователя и проверяемым источникам. Перед подачей документа проверьте персональные данные, суммы, доказательства, подсудность и госпошлину.',
    privacyText: 'Материалы используются только для консультации и подготовки документов. Данные Mini App можно удалить из профиля.',
    accept: 'Принимаю условия', decline: 'Не принимаю',
    heroTitle: 'Профессиональный AI-юрист', heroText: 'Консультации, анализ материалов, документы и контроль качества в одном рабочем пространстве.',
    startConsult: 'Начать консультацию', consultation: 'Консультация', consultationSub: 'Правовой анализ с проверкой источников',
    prepare: 'Подготовить документ', prepareSub: 'Production Word-документы KORGAN', myCases: 'Мои дела', casesSub: 'Материалы, консультации и готовые документы',
    privacy: 'Конфиденциальность', privacySub: 'Согласие, язык и управление данными', connected: 'KORGAN подключён', connecting: 'Проверяю соединение…', down: 'Сервис временно недоступен',
    systemReady: 'Система готова', systemProblem: 'Проблема соединения', retry: 'Повторить',
    sessionExpired: 'Сессия Telegram истекла. Закройте и откройте KORGAN заново — данные сохранены.',
    notFound: 'Эти данные больше не найдены. Обновите список дел.',
    selectDoc: 'Выбор документа', searchDoc: 'Поиск документа', documents: 'Документы', docPrice: 'Подготовка документа',
    newCase: 'Новое дело', tell: 'Расскажите, что произошло', tellSub: 'Опишите ситуацию или сразу загрузите PDF, DOCX, TXT либо фотографии. Все материалы будут привязаны к одному делу.',
    placeholder: 'Стороны, отношения/договор, даты, суммы, нарушение, доказательства, позиция и желаемый результат…', create: 'Создать дело', creating: 'Создаю дело…',
    addFile: 'Загрузить документы / фото', processing: 'Обрабатываю материалы…', selected: 'Выбрано', materials: 'Материалы дела', files: 'Файлов',
    consultCase: 'Консультация по делу', generate: 'Подготовить документ', generating: 'Проверяю право и формирую Word…', deleteCase: 'Удалить дело',
    caseCreated: 'Дело создано', materialsLoaded: 'Материалы загружены', docReady: 'Документ готов', noCases: 'Дел пока нет', noCasesSub: 'Создайте первое дело и добавьте факты или документы.', createNew: 'Создать новое дело',
    download: 'Скачать DOCX', downloadExisting: 'Скачать готовый DOCX', liveReview: 'Проверка живым юристом',
    message: 'Напишите юридический вопрос…', checking: 'Проверяю право и источники…', sources: 'Источники', freeRemaining: 'Бесплатных консультаций осталось',
    paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите одну консультацию через Kaspi и загрузите полный чек. После автоматической проверки ответ продолжится по этому же вопросу.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек', checkingReceipt: 'Проверяю чек…', retryPaid: 'Повторить ответ без новой оплаты', paidSaved: 'Оплата сохранена. Повторно платить не нужно.',
    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.',
    waitingAdmin: 'Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Теперь можно запустить юридический анализ и генерацию Word. Новая оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',
    paymentRejected: 'Оплата не подтверждена. Загрузите другой полный чек.', manualCheck: 'Ручное подтверждение', manualCheckSub: 'AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.',
    filingReady: 'Готов к финальной проверке юристом', preliminary: 'Предварительный документ', verified: 'Автоматические проверки пройдены. Перед использованием документ должен проверить юрист.', needsCheck: 'Требуется проверка', quality: 'Качество', status: 'Статус', check: 'Проверка',
    pricing: 'Тарифы и лимиты', freePerDay: 'Бесплатных консультаций в день', consultPrice: 'Консультация после лимита', language: 'Язык', deleteAll: 'Удалить все мои данные',
    dataControl: 'Данные под контролем', dataControlSub: 'Mini App использует отдельный API и не изменяет production Telegram‑агента.', runtime: 'Юридическое ядро', secure: 'Защищённое хранение', refresh: 'Обновить', support: 'Техподдержка',
    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.',
    admin: 'Проверка оплат', adminTitle: 'Оплаты документов', adminEmpty: 'Чеков на ручную проверку нет', approve: 'Подтвердить', reject: 'Отклонить', adminRefresh: 'Обновить список', payer: 'Плательщик', recipient: 'Получатель', transaction: 'Операция', dateTime: 'Дата / время', anomalies: 'Аномалии AI', clientRef: 'Клиент', order: 'Заказ',
    preparing: 'Документ готовится', preparingText: 'Работа идёт на сервере. Mini App можно закрыть — подготовка не прервётся, а состояние вернётся при следующем открытии дела.',
    preparingFailed: 'Подготовка не завершилась', retryGeneration: 'Повторить подготовку без новой оплаты', backToCase: 'Вернуться к делу', progress: 'Готовность',
  },
  kk: {
    home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль', help: 'Көмек',
    consentTitle: 'KORGAN Legal AI пайдалану шарттары', consentText: 'KORGAN — Қазақстан Республикасының құқығына арналған жасанды интеллект жүйесі. Жауаптар мен құжаттар пайдаланушы деректері және тексерілетін дереккөздер бойынша жасалады. Құжатты бергенге дейін дербес деректерді, сомаларды, дәлелдемелерді, соттылықты және мемлекеттік бажды тексеріңіз.', privacyText: 'Материалдар тек кеңес беру және құжат дайындау үшін пайдаланылады. Mini App деректерін профильден жоюға болады.', accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын',
    heroTitle: 'Кәсіби AI-заңгер', heroText: 'Кеңес, материалдарды талдау, құжаттар және сапаны бақылау бір жұмыс кеңістігінде.', startConsult: 'Кеңесті бастау', consultation: 'Кеңес', consultationSub: 'Дереккөздерді тексеретін құқықтық талдау', prepare: 'Құжат дайындау', prepareSub: 'KORGAN production Word-құжаттары', myCases: 'Менің істерім', casesSub: 'Материалдар, кеңестер және дайын құжаттар', privacy: 'Құпиялылық', privacySub: 'Келісім, тіл және деректерді басқару', connected: 'KORGAN қосылды', connecting: 'Қосылым тексерілуде…', down: 'Қызмет уақытша қолжетімсіз', systemReady: 'Жүйе дайын', systemProblem: 'Қосылым мәселесі', retry: 'Қайталау',
    sessionExpired: 'Telegram сессиясының мерзімі бітті. KORGAN-ды жауып, қайта ашыңыз — деректер сақталды.',
    notFound: 'Бұл деректер табылмады. Істер тізімін жаңартыңыз.',
    selectDoc: 'Құжатты таңдау', searchDoc: 'Құжатты іздеу', documents: 'Құжаттар', docPrice: 'Құжат дайындау', newCase: 'Жаңа іс', tell: 'Не болғанын жазыңыз', tellSub: 'Жағдайды сипаттаңыз немесе PDF, DOCX, TXT не фотосуреттерді бірден жүктеңіз. Барлық материал бір іске бекітіледі.', placeholder: 'Тараптар, қатынас/шарт, күндер, сомалар, бұзушылық, дәлелдер, ұстаным және қажетті нәтиже…', create: 'Іс құру', creating: 'Іс құрылуда…', addFile: 'Құжаттар / фото жүктеу', processing: 'Материалдар өңделуде…', selected: 'Таңдалды', materials: 'Іс материалдары', files: 'Файлдар', consultCase: 'Іс бойынша кеңес', generate: 'Құжат дайындау', generating: 'Құқық тексеріліп, Word жасалуда…', deleteCase: 'Істі жою', caseCreated: 'Іс құрылды', materialsLoaded: 'Материалдар жүктелді', docReady: 'Құжат дайын', noCases: 'Әзірге іс жоқ', noCasesSub: 'Бірінші істі құрып, фактілер немесе құжаттар қосыңыз.', createNew: 'Жаңа іс құру', download: 'DOCX жүктеу', downloadExisting: 'Дайын DOCX жүктеу', liveReview: 'Тірі заңгердің тексеруі',
    message: 'Заңдық сұрағыңызды жазыңыз…', checking: 'Құқық пен дереккөздер тексерілуде…', sources: 'Дереккөздер', freeRemaining: 'Қалған тегін кеңес', paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Kaspi арқылы бір кеңес ақысын төлеп, толық чекті жүктеңіз. Автоматты тексеруден кейін осы сұрақ бойынша жауап жалғасады.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу', checkingReceipt: 'Чек тексерілуде…', retryPaid: 'Жаңа төлемсіз жауапты қайталау', paidSaved: 'Төлем сақталды. Қайта төлеу қажет емес.',
    documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.', waitingAdmin: 'Чек алдын ала тексеруден өтті. Kaspi Pay тарихы бойынша қолмен растау күтілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Енді құқықтық талдау мен Word генерациясын бастауға болады. Қайта төлем қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Басқа толық чекті жүктеңіз.', manualCheck: 'Қолмен растау', manualCheckSub: 'AI банк төлемін түпкілікті растамайды — әкімші нақты төлемді тексереді.', filingReady: 'Заңгердің қорытынды тексеруіне дайын', preliminary: 'Алдын ала құжат', verified: 'Автоматты тексерулер аяқталды. Пайдаланар алдында құжатты заңгер тексеруі тиіс.', needsCheck: 'Тексеру қажет', quality: 'Сапа', status: 'Мәртебе', check: 'Тексеру', pricing: 'Тарифтер мен лимиттер', freePerDay: 'Күніне тегін кеңес', consultPrice: 'Лимиттен кейінгі кеңес', language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', runtime: 'Заңдық ядро', secure: 'Қорғалған сақтау', refresh: 'Жаңарту', support: 'Техқолдау', helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем мен қолмен растаудан бұрын басталмайды.',
    admin: 'Төлемдерді тексеру', adminTitle: 'Құжат төлемдері', adminEmpty: 'Қолмен тексерілетін чек жоқ', approve: 'Растау', reject: 'Қабылдамау', adminRefresh: 'Тізімді жаңарту', payer: 'Төлеуші', recipient: 'Алушы', transaction: 'Операция', dateTime: 'Күні / уақыты', anomalies: 'AI аномалиялары', clientRef: 'Клиент', order: 'Тапсырыс',
    preparing: 'Құжат дайындалуда', preparingText: 'Жұмыс серверде жүріп жатыр. Mini App-ты жабуға болады — дайындау тоқтамайды, ал күйі істі келесі ашқанда қайта көрінеді.',
    preparingFailed: 'Дайындау аяқталмады', retryGeneration: 'Жаңа төлемсіз дайындауды қайталау', backToCase: 'Іске оралу', progress: 'Дайындық',
  },
};

// Сервер называет стадии своими служебными именами. Клиенту показывается то,
// что происходит с его документом, а не название шага конвейера.
const STAGE_TEXT = {
  ru: {
    queued: 'Дело принято в работу', starting: 'Материалы дела подготовлены к анализу',
    legal_research: 'Проверяю право Республики Казахстан и источники',
    quality_control: 'Проверяю факты, суммы и требования документа',
    document_render: 'Формирую документ Word', completed: 'Документ готов',
    interrupted: 'Работа прервалась и может быть продолжена', failed: 'Подготовка не завершилась',
  },
  kk: {
    queued: 'Іс жұмысқа қабылданды', starting: 'Іс материалдары талдауға дайындалды',
    legal_research: 'Қазақстан Республикасының құқығы мен дереккөздер тексерілуде',
    quality_control: 'Фактілер, сомалар және құжат талаптары тексерілуде',
    document_render: 'Word құжаты жасалуда', completed: 'Құжат дайын',
    interrupted: 'Жұмыс үзілді және жалғастырылуы мүмкін', failed: 'Дайындау аяқталмады',
  },
};
const stageText = (stage, lang) => STAGE_TEXT[lang]?.[stage] || STAGE_TEXT[lang]?.queued || '';

const money = value => `${Number(value || 0).toLocaleString('ru-RU')} ₸`;
const docText = (id, lang) => DOCUMENTS.find(x => x.id === id)?.[lang] || ['KORGAN Legal AI', ''];
const safeUrl = value => /^https?:\/\//i.test(String(value || '').trim()) ? String(value).trim() : '';
const sourceLabel = value => { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return String(value || ''); } };

// Карточка живёт внутри .action-grid, которой владеет React. Раньше её дописывал
// отдельный модуль, а наблюдатель за всем документом возвращал её на место после
// каждой перерисовки — два владельца одного узла.
function PersonalLawyerCard({ language }) {
  const copy = personalLawyerCopy(language);
  return <button type="button" className="action-card personal-lawyer-card" aria-label={copy.aria} onClick={() => { haptic(); window.open(PERSONAL_LAWYER_URL, '_blank', 'noopener,noreferrer'); }}><div className="personal-lawyer-icon" aria-hidden="true">⚖</div><div className="personal-lawyer-copy"><span className="section-kicker">{copy.kicker}</span><h2>{copy.title}</h2><p>{copy.description}</p></div><span className="personal-lawyer-arrow" aria-hidden="true">→</span></button>;
}

function App() {
  const initial = loadState();
  const [screen, setScreen] = useState('home');
  const [language, setLanguage] = useState(initial.language || 'ru');
  const [consent, setConsent] = useState(null);
  const [connection, setConnection] = useState('checking');
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [pricing, setPricing] = useState(null);
  const [telegramUser, setTelegramUser] = useState(null);
  // Занятость одна на всё приложение — действия выполняются по одному, и на
  // время любого из них кнопки гаснут. Но подпись на кнопке — отчёт о работе, и
  // общей занятости для неё мало: нажатое «Скачать» объявлялось соседней
  // кнопкой как «Проверяю право и формирую Word…». Поэтому занятость называет
  // себя, а `busy` остаётся тем же общим замком.
  const [busyAction, setBusyAction] = useState('');
  const busy = Boolean(busyAction);
  const setBusy = value => setBusyAction(value === true ? 'action' : value === false ? '' : String(value || ''));
  const [notice, setNoticeState] = useState('');
  const [cases, setCases] = useState([]);
  const [activeCase, setActiveCase] = useState(null);
  const [selectedDocument, setSelectedDocument] = useState(initial.draft?.documentType || 'claim');
  const [caseText, setCaseText] = useState(initial.draft?.description || '');
  const [pendingFiles, setPendingFiles] = useState([]);
  const [query, setQuery] = useState('');
  const [chat, setChat] = useState([]);
  const [message, setMessage] = useState('');
  const [freeRemaining, setFreeRemaining] = useState(null);
  const [consultPayment, setConsultPayment] = useState(null);
  const [receiptBusy, setReceiptBusy] = useState(false);
  const [documentResult, setDocumentResult] = useState(null);
  const [docPayment, setDocPayment] = useState(null);
  const [generation, setGeneration] = useState(null);
  const [adminOrders, setAdminOrders] = useState([]);
  const [adminBusy, setAdminBusy] = useState(false);
  const bootstrap = useRef(null);
  // Открытие дела переживает смену экрана и повторное нажатие только как
  // поколение: устаревший ответ ничего не меняет.
  const latestCase = useRef(createLatestAction());
  // Список дел перечитывается из шести мест, и ответы возвращаются вперемешку:
  // применяется только самый свежий, иначе удалённое дело возвращается в список.
  const latestCases = useRef(createLatestAction());
  // Показанное сообщение читается из обработчика опроса, который был создан
  // прежним рендером: значение состояния там устарело, а ссылка — нет.
  const shownNotice = useRef('');
  const pollNotice = useRef('');
  // Тем же способом читается и текущий экран: обработчик знает из замыкания тот
  // экран, на котором его нажали, а ссылка — тот, где пользователь сейчас.
  const screenRef = useRef(screen);
  screenRef.current = screen;
  // Любая другая запись отменяет право опроса снять сообщение: показано уже не
  // то, что он писал, и позже он снял бы чужое вместо своего.
  const writeNotice = text => { shownNotice.current = String(text || ''); pollNotice.current = ''; setNoticeState(shownNotice.current); };
  // Уведомление принадлежит экрану, на котором действие началось. Кнопки
  // навигации не гаснут во время работы, поэтому долгий запрос легко оставить в
  // пути и уйти; его ответ писал сообщение туда, где пользователь уже стоит —
  // «Обработано файлов: 1» над списком дел ничего не объясняет и читается как
  // предупреждение. Опоздавший ответ теперь молчит.
  const setNotice = text => { if (screenRef.current === screen) writeNotice(text); };
  if (bootstrap.current === null) {
    bootstrap.current = createBootstrapSession({
      api: korganApi,
      isBackendConnected,
      termsVersion: TERMS_VERSION,
    });
  }
  const t = L[language];
  const backendOk = connection === 'ok';
  // Что рисуется и что подсвечено в навигации — один и тот же ответ. Экран без
  // своих данных заменяется ближайшим осмысленным, а не молча главной.
  const view = resolveScreen(screen, {
    hasCase: Boolean(activeCase),
    hasPayment: Boolean(docPayment),
    hasGeneration: Boolean(generation),
    hasDocument: Boolean(documentResult),
  });

  const resetChat = () => {
    setConsultPayment(null);
    setChat([{ from: 'ai', text: language === 'kk' ? 'Заңдық сұрағыңызды жазыңыз. Мен Қазақстан Республикасының құқығын және дереккөздерді тексеремін.' : 'Опишите юридический вопрос. Я проверю право Республики Казахстан и источники.' }]);
  };

  const boot = async () => {
    setConnection('checking'); setNotice('');
    const result = await bootstrap.current.run();
    if (result.kind === 'stale') return;
    if (result.kind === 'error' || result.kind === 'unavailable') {
      setConnection('down');
      setNotice(clientMessage(result.error));
      return;
    }
    setRuntimeInfo(result.health);
    setConsent(result.consent);
    setPricing(result.pricing);
    latestCases.current.invalidate();
    setCases(result.cases);
    setConnection('ok');
  };

  useEffect(() => {
    initTelegram(); setTelegramUser(getTelegramUser()); boot();
    return () => bootstrap.current.cancel();
  }, []);
  useEffect(() => { if (!activeCase) resetChat(); }, [language]);
  useEffect(() => {
    if (view !== 'doc-payment' || docPayment?.status !== 'awaiting_admin' || !docPayment?.order_id) return undefined;
    return startDocumentPaymentPolling({
      orderId: docPayment.order_id,
      fetchStatus: korganApi.documentPaymentStatus,
      onPayment: payment => { reportPolling(null); setDocPayment(payment); },
      onError: reportPolling,
    });
  }, [view, docPayment?.status, docPayment?.order_id, t.down]);
  // Опрос привязан к задаче, а не к процентам: обновление прогресса не должно
  // перезапускать проверку, иначе на экране одновременно жили бы два опроса.
  useEffect(() => {
    if (view !== 'generating' || !generation?.jobId || generation.status === 'failed') return undefined;
    return startGenerationPolling({
      jobId: generation.jobId,
      fetchStatus: korganApi.generationStatus,
      onProgress: job => { reportPolling(null); setGeneration(job); },
      onReady: document => { reportPolling(null); applyDocument(document); refreshCases().catch(() => {}); },
      onFailed: job => { reportPolling(null); setGeneration(job); },
      onError: reportPolling,
    });
  }, [view, generation?.jobId, generation?.status]);

  const filteredDocuments = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? DOCUMENTS.filter(item => item[language].join(' ').toLowerCase().includes(q)) : DOCUMENTS;
  }, [query, language]);

  // Служебный ответ сервера не является текстом для клиента: и отказ в подписи
  // Telegram, и «Case not found», и внутренние имена в «KORGAN generator
  // unavailable: …» англоязычны и ничего не объясняют. Правило — в clientMessage.
  const clientMessage = error => messageForClient(error, t);
  // Сбой опроса — сообщение самого опроса: он снимает его, как только ответ
  // снова получен, и не трогает написанного действием пользователя.
  const reportPolling = error => {
    // Опрос своего экрана и заканчивается вместе с ним: с чужого он не пишет и
    // не запоминает написанного — иначе позже снял бы вместо своего чужое.
    if (screenRef.current !== screen) return;
    const update = pollingNoticeUpdate({
      shown: shownNotice.current,
      owned: pollNotice.current,
      text: error ? clientMessage(error) : '',
    });
    setNotice(update.shown);
    pollNotice.current = update.owned;
  };
  // Уведомление принадлежит экрану, на котором возникло. Смена экрана гасит его
  // всегда, каким бы способом переход ни произошёл: иначе временная ошибка
  // опроса переезжает на экран готового документа и противоречит ему. Гасит
  // напрямую, минуя проверку экрана: переход и есть тот случай, когда чужое
  // сообщение обязано исчезнуть.
  const showScreen = next => { latestCase.current.invalidate(); writeNotice(''); setScreen(next); };
  const go = next => { haptic(); showScreen(next); };
  const switchLanguage = next => { setLanguage(next); persistLanguage(next); };
  const refreshCases = async () => {
    const mine = latestCases.current.start();
    const result = await korganApi.listCases();
    const items = result.cases || [];
    if (!mine()) return items;
    setCases(items);
    return items;
  };

  // Готовность объявляется только описанием реально сохранённого документа:
  // экран выпуска нельзя открыть на описании ещё идущей задачи.
  const applyDocument = document => {
    setDocumentResult(document); setDocPayment(null); setGeneration(null);
    setActiveCase(prev => prev ? { ...prev, status: document.status, title: document.title, verification_status: document.verification_status, has_document: true, filing_ready: document.filing_ready, release_status: document.release_status, quality_score: document.quality_score } : prev);
    showScreen('ready');
  };

  const applyGenerationState = async result => {
    const state = interpretGeneration(result);
    if (state.status === 'payment_required') { setGeneration(null); setDocPayment(state.payment); showScreen('doc-payment'); return; }
    if (state.status === 'ready') { applyDocument(state.document); try { await refreshCases(); } catch {} return; }
    if (state.status === 'idle') { setGeneration(null); return; }
    setGeneration(state.job); setDocPayment(null); showScreen('generating');
  };

  const acceptTerms = async () => {
    setBusy(true); setNotice('');
    try { await korganApi.acceptConsent(TERMS_VERSION); await boot(); }
    catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };
  const declineTerms = async () => {
    try { if (isBackendConnected()) await korganApi.declineConsent(TERMS_VERSION); } catch {}
    clearAllLocalData(); window.Telegram?.WebApp?.close?.();
  };

  const chooseDocument = id => { setSelectedDocument(id); setPendingFiles([]); saveDraft({ documentType: id }); go('new-case'); };
  const saveCaseText = value => { setCaseText(value); saveDraft({ description: value, documentType: selectedDocument }); };
  const chooseInitialFiles = event => { const files = Array.from(event.target.files || []); event.target.value = ''; setPendingFiles(files); };

  const createCase = async () => {
    if ((!caseText.trim() && !pendingFiles.length) || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.createCase({ description: caseText.trim(), document_type: selectedDocument, language });
      let item = result.case;
      if (pendingFiles.length) {
        await korganApi.uploadMaterials(item.id, pendingFiles, ({ result: uploaded }) => { item = uploaded.case || item; setActiveCase(item); });
      }
      setActiveCase(item); setDocumentResult(null); setDocPayment(null); resetChat();
      // Дело создано и материалы загружены — это подтвердил сервер. Обновление
      // списка стояло перед очисткой черновика и переходом, и его сбой обрывал
      // цепочку: пользователь оставался на форме со своим текстом и файлами,
      // читал ошибку и нажимал «Создать дело» ещё раз — в списке появлялось
      // второе такое же дело. Сверка со списком идёт следом.
      clearLocalCaseData(); setCaseText(''); setPendingFiles([]); showScreen('case');
      refreshCases().catch(() => {});
    } catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };

  const openCase = async item => {
    // Список дел не гасит свои кнопки, поэтому от второго нажатия защищается
    // сам обработчик: иначе ответ на дело A перезаписывал бы открытое дело B.
    if (busy) return;
    let mine = latestCase.current.start();
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getCase(item.id); const detail = result.case;
      if (!mine()) return;
      setActiveCase(detail); setDocumentResult(null); setDocPayment(null); setConsultPayment(null); setGeneration(null);
      const restored = (detail.conversation || []).map(entry => ({ from: entry.role === 'user' ? 'user' : 'ai', text: entry.text || '', sources: entry.sources || [] }));
      setChat(restored.length ? restored : [{ from: 'ai', text: language === 'kk' ? 'Осы іс бойынша сұрағыңызды жазыңыз.' : 'Задайте вопрос по этому делу.' }]); showScreen('case');
      mine = latestCase.current.start();
      // Подготовка переживает закрытие Mini App, а выданный при запуске
      // идентификатор задачи — нет. Незавершённая работа возвращается на экран,
      // а завершённая ничего не перехватывает: дело открыли, а не документ.
      try {
        const resumed = interpretGeneration(await korganApi.caseGeneration(detail.id));
        if (!mine()) return;
        if (resumed.status === 'running' || resumed.status === 'failed') { setGeneration(resumed.job); showScreen('generating'); }
      } catch { /* дело открыто; состояние подготовки узнаётся повторным запуском */ }
    } catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };

  const uploadMaterial = async event => {
    const files = Array.from(event.target.files || []); event.target.value = '';
    if (!files.length || !activeCase || busy) return;
    setBusy('upload'); setNotice('');
    try {
      let latest = activeCase;
      await korganApi.uploadMaterials(activeCase.id, files, ({ result }) => { latest = result.case || latest; setActiveCase(latest); });
      setActiveCase(latest); setDocPayment(null);
      // Материалы приняты сервером, и счётчик файлов на экране дела уже вырос.
      // Обновление списка дел стояло между отправкой и сообщением, и его сбой
      // уводил обработчик в разбор ошибок: успешная загрузка объявлялась
      // неудачной, а пользователь грузил те же файлы второй раз. Списка на
      // этом экране нет, поэтому его сверка уходит за результат загрузки.
      setNotice(language === 'kk' ? `${files.length} файл өңделді.` : `Обработано файлов: ${files.length}.`);
      refreshCases().catch(() => {});
    } catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };

  const appendAnswer = result => {
    if (String(result?.answer || '').trim()) setChat(prev => [...prev, { from: 'ai', text: result.answer, sources: result.sources || [] }]);
    if (typeof result?.free_remaining === 'number') setFreeRemaining(result.free_remaining);
  };
  const sendMessage = async () => {
    const value = message.trim(); if (!value || busy || !backendOk || consultPayment) return;
    setMessage(''); setChat(prev => [...prev, { from: 'user', text: value }]); setBusy(true);
    try {
      const result = await korganApi.consultation(value, activeCase?.id || null, activeCase?.language || language);
      if (result.payment_required && result.payment) { setFreeRemaining(0); setConsultPayment({ ...result.payment, paidPending: false }); }
      else appendAnswer(result);
    } catch (error) { setChat(prev => [...prev, { from: 'ai error', text: clientMessage(error) }]); }
    finally { setBusy(false); }
  };
  const uploadConsultReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !consultPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, file); appendAnswer(result); setConsultPayment(null); }
    catch (error) { if (error?.status === 503) { setConsultPayment(prev => ({ ...prev, paidPending: true })); setNotice(t.paidSaved); } else setNotice(clientMessage(error)); }
    finally { setReceiptBusy(false); }
  };
  const retryPaidConsultation = async () => {
    if (!consultPayment?.order_id || busy) return; setBusy(true); setNotice('');
    try { const result = await korganApi.retryPaidConsultation(consultPayment.order_id); appendAnswer(result); setConsultPayment(null); }
    catch (error) { setNotice(clientMessage(error)); } finally { setBusy(false); }
  };

  // Запуск подготовки отвечает описанием задачи, а не готовым документом:
  // работа продолжается на сервере, и экран следует за её состоянием.
  const generateDocument = async () => {
    if (!activeCase || busy) return; setBusy('generate'); setNotice('');
    try { await applyGenerationState(await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language)); }
    catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };
  // Повтор берёт ту же оплаченную задачу, поэтому второй оплаты не возникает.
  const retryGeneration = async () => {
    if (!generation?.jobId || !generation.retryable || busy) return; setBusy(true); setNotice('');
    try { await applyGenerationState(await korganApi.retryGeneration(generation.jobId)); }
    catch (error) { setNotice(clientMessage(error)); }
    finally { setBusy(false); }
  };
  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(requireDocumentPayment(result)); setNotice(result.message || t.waitingAdmin); }
    catch (error) { setNotice(clientMessage(error)); } finally { setReceiptBusy(false); }
  };
  const refreshDocPayment = async () => {
    if (!docPayment?.order_id || busy) return; setBusy(true); setNotice('');
    try { const result = await korganApi.documentPaymentStatus(docPayment.order_id); setDocPayment(requireDocumentPayment(result)); }
    catch (error) { setNotice(clientMessage(error)); } finally { setBusy(false); }
  };
  const deliverActiveDocument = async () => {
    if (!activeCase || busy) return; setBusy(true); setNotice('');
    try {
      const tg = getTelegramWebApp();
      const result = await deliverDocument(activeCase.id, {
        insideTelegram: Boolean(tg),
        api: korganApi,
        openUrl: (url, filename) => openSignedDocument(url, filename, { telegram: null }),
      });
      if (result.message) setNotice(result.message);
    } catch (error) { setNotice(clientMessage(error)); } finally { setBusy(false); }
  };

  // Удаление подтверждает сервер, поэтому карточка убирается из списка сразу и
  // своими силами. Раньше на пути к списку стояло его перечитывание: моргнувшая
  // сеть обрывала удаление до перехода, и в списке оставалось дело, которого на
  // сервере уже нет, — нажатие на него отвечало «дело не найдено». Сверка с
  // сервером осталась, но теперь она уточняет, а не решает.
  const deleteCurrentCase = async () => {
    if (!activeCase || busy) return;
    if (!window.confirm(language === 'kk' ? 'Бұл істі жою керек пе?' : 'Удалить это дело и все его данные?')) return;
    const removed = activeCase.id;
    setBusy(true);
    try {
      await korganApi.deleteCase(removed);
      setActiveCase(null); setDocPayment(null);
      latestCases.current.invalidate();
      setCases(prev => prev.filter(item => item.id !== removed));
      showScreen('cases');
      refreshCases().catch(() => {});
    } catch (error) { setNotice(clientMessage(error)); } finally { setBusy(false); }
  };
  const deleteAllData = async () => {
    if (busy) return;
    if (!window.confirm(language === 'kk' ? 'Барлық Mini App деректерін жою керек пе?' : 'Удалить все данные Mini App и все дела?')) return;
    setBusy(true); try { await korganApi.deleteMyData(); clearAllLocalData(); latestCases.current.invalidate(); setCases([]); setActiveCase(null); setConsent(false); showScreen('home'); } catch (error) { setNotice(clientMessage(error)); } finally { setBusy(false); }
  };

  const loadAdminOrders = async () => {
    setAdminBusy(true); setNotice('');
    try { const result = await korganApi.adminDocumentPayments('awaiting_admin'); setAdminOrders(result.orders || []); }
    catch (error) { setNotice(clientMessage(error)); } finally { setAdminBusy(false); }
  };
  // Экран проверки оплат загружает заказы сам. Раньше их грузил переход, уже
  // сменивший экран: запрос шёл от обработчика прежнего экрана, и сообщение о
  // сбое загрузки считалось чужим — список молча оставался пустым.
  const openAdmin = () => { showScreen('admin-payments'); };
  useEffect(() => { if (view === 'admin-payments') loadAdminOrders(); }, [view]);
  const decideAdminOrder = async (orderId, approved) => {
    const question = approved ? (language === 'kk' ? 'Kaspi Pay тарихында осы төлем нақты расталды ма?' : 'Вы действительно сверили этот платёж в истории Kaspi Pay?') : (language === 'kk' ? 'Бұл төлемді қабылдамау керек пе?' : 'Отклонить эту оплату?');
    if (!window.confirm(question)) return;
    setAdminBusy(true); setNotice('');
    try {
      await korganApi.adminDocumentPaymentDecision(orderId, approved, approved ? 'Kaspi Pay manually confirmed' : 'Payment not confirmed in Kaspi Pay');
      // Очередь показывает только нерешённые заказы, а решение уже принято
      // сервером. Раньше заказ уходил из очереди только вместе с успешным
      // перечитыванием списка, а оно гасит свои ошибки само: на сбое сети
      // подтверждённая оплата оставалась в очереди, и оператор решал её второй
      // раз. Сверка с сервером идёт следом и ничего больше не решает.
      setAdminOrders(prev => prev.filter(order => order.order_id !== orderId));
      await loadAdminOrders();
    }
    catch (error) { setNotice(clientMessage(error)); } finally { setAdminBusy(false); }
  };

  const Header = ({ title, back = 'home' }) => <header className="subbar"><button className="icon-btn" onClick={() => go(back)}><ArrowLeft size={20}/></button><strong>{title}</strong><span className="header-spacer"/></header>;
  // Переход происходит по нажатию, а обновление списка догоняет: у кнопок
  // навигации нет индикатора занятости, поэтому ожидание ответа сервера перед
  // сменой экрана выглядело зависанием, а на разорванной связи держало экран до
  // таймаута. Опоздавший ответ безопасен — `refreshCases` защищён поколением.
  const BottomNav = () => <nav className="bottom-nav">
    <button className={view === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>
    <button className={view === 'cases' ? 'active' : ''} onClick={() => { go('cases'); refreshCases().catch(() => {}); }}><FolderOpen size={20}/><span>{t.cases}</span></button>
    <button className={view === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>
    <button className={view === 'help' ? 'active' : ''} onClick={() => go('help')}><CircleHelp size={20}/><span>{t.help}</span></button>
    <button className={view === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>
  </nav>;
  const ConnectionBanner = () => connection === 'down' ? <div className="connection-banner error-banner"><WifiOff size={18}/><div><strong>{t.systemProblem}</strong><small>{t.down}</small></div><button onClick={boot}><RefreshCw size={17}/>{t.retry}</button></div> : null;
  const Sources = ({ items = [] }) => !items.length ? null : <div className="source-list"><span>{t.sources}</span>{items.map((source, i) => { const url = safeUrl(source); return url ? <a key={`${source}-${i}`} href={url} target="_blank" rel="noreferrer"><Link2 size={13}/>{sourceLabel(url)}<ExternalLink size={12}/></a> : <span className="source-chip" key={`${source}-${i}`}><Link2 size={13}/>{source}</span>; })}</div>;

  if (consent === null) return <div className="app-shell consent-shell"><main className="page consent-page"><div className="success-ring preliminary-ring">{connection === 'down' ? <WifiOff size={38}/> : <LoaderCircle className="spin" size={38}/>}</div><h1>{connection === 'down' ? t.systemProblem : t.connecting}</h1>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{connection === 'down' && <button className="primary wide" onClick={boot}><RefreshCw size={17}/>{t.retry}</button>}</main></div>;

  if (!consent) return <div className="app-shell consent-shell"><main className="page consent-page">
    <div className="brand-mark large"><Scale size={28}/></div><div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div>
    <h1>{t.consentTitle}</h1><section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section><section className="privacy-card static"><LockKeyhole size={22}/><div><strong>{t.privacy}</strong><p>{t.privacyText}</p></div></section>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="primary wide" disabled={busy} onClick={acceptTerms}>{busy ? <LoaderCircle className="spin" size={18}/> : <ShieldCheck size={18}/>} {t.accept}</button><button className="secondary wide" onClick={declineTerms}>{t.decline}</button><small>v. {TERMS_VERSION}</small>
  </main></div>;

  if (view === 'documents') return <div className="app-shell"><Header title={t.selectDoc}/><main className="page"><ConnectionBanner/><div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t.searchDoc}/></div>{pricing?.document_payments_enabled && <div className="price-note"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · {t.manualCheck}</span></div>}<div className="section-kicker list-kicker">{t.documents}</div><div className="list-card">{filteredDocuments.map(item => { const [title, subtitle] = item[language]; const Icon = item.icon; return <button className="list-row" key={item.id} onClick={() => chooseDocument(item.id)}><span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/></button>; })}</div></main><BottomNav/></div>;

  if (view === 'new-case') { const [title] = docText(selectedDocument, language); return <div className="app-shell"><Header title={t.newCase} back="documents"/><main className="page creation-page"><ConnectionBanner/><div className="big-title"><span className="eyebrow">{title}</span><h1>{t.tell}</h1><p>{t.tellSub}</p></div><textarea className="case-input" value={caseText} onChange={e => saveCaseText(e.target.value)} maxLength={8000} placeholder={t.placeholder}/><div className="input-meta"><Sparkles size={17}/><span>{caseText.length}/8000</span></div><label className="secondary wide"><Paperclip size={18}/>{t.addFile}<input className="hidden-input" multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={chooseInitialFiles}/></label>{pendingFiles.length > 0 && <div className="success-note">{t.selected}: {pendingFiles.map(f => f.name).join(', ')}</div>}{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="primary wide" disabled={(!caseText.trim() && !pendingFiles.length) || busy || !backendOk} onClick={createCase}>{busy ? <LoaderCircle className="spin" size={18}/> : <ArrowRight size={18}/>} {busy ? t.creating : t.create}</button></main></div>; }

  if (view === 'case') {
    if (!activeCase) return <div className="app-shell"><Header title={t.cases} back="cases"/><main className="page"><p>{t.noCases}</p></main><BottomNav/></div>;
    const [title] = docText(activeCase.document_type, language); const statusText = activeCase.status === 'document_ready' ? t.docReady : activeCase.status === 'materials_ready' ? t.materialsLoaded : t.caseCreated;
    return <div className="app-shell"><Header title={activeCase.id} back="cases"/><main className="page"><ConnectionBanner/><section className="status-card"><div><span className="section-kicker">{t.status}</span><h2>{statusText}</h2></div><span className="pill success">{(activeCase.language || language).toUpperCase()}</span></section><section className="analysis-card"><div className="card-head"><div><span className="section-kicker">{t.materials}</span><h2>{activeCase.title || title}</h2></div><Sparkles size={22}/></div>{activeCase.description && <p className="case-description">{activeCase.description}</p>}<div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count || 0}</strong></div>{activeCase.material_names?.length > 0 && <div className="material-list">{activeCase.material_names.map(name => <span key={name}><Paperclip size={13}/>{name}</span>)}</div>}{activeCase.verification_status && <div className="fact"><span>{t.check}</span><strong>{activeCase.filing_ready ? t.verified : t.needsCheck}</strong></div>}{typeof activeCase.quality_score === 'number' && <div className="fact"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}</section>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<label className="secondary wide"><Paperclip size={18}/>{busyAction === 'upload' ? t.processing : t.addFile}<input className="hidden-input" disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterial}/></label><button className="secondary wide" onClick={() => go('chat')}><MessageCircle size={18}/>{t.consultCase}</button>{activeCase.has_document && <button className="secondary wide" disabled={busy} onClick={deliverActiveDocument}><Download size={18}/>{t.downloadExisting}</button>}<button className="primary wide" disabled={busy || !backendOk} onClick={generateDocument}>{busyAction === 'generate' ? <LoaderCircle className="spin" size={18}/> : <FileText size={18}/>} {busyAction === 'generate' ? t.generating : pricing?.document_payments_enabled ? `${t.generate} · ${money(pricing.document_price_kzt)}` : t.generate}</button><button className="secondary wide danger" disabled={busy} onClick={deleteCurrentCase}><Trash2 size={18}/>{t.deleteCase}</button></main><BottomNav/></div>;
  }

  if (view === 'chat') return <div className="app-shell chat-shell"><Header title={activeCase ? `${t.lawyer} · ${activeCase.id}` : t.lawyer}/><main className="chat-page"><div className={`connection-note ${backendOk ? '' : 'offline'}`}><span className={backendOk ? 'dot on' : 'dot'}/>{connection === 'checking' ? t.connecting : backendOk ? t.connected : t.down}</div>{freeRemaining !== null && <div className="quota-note"><BadgeCheck size={15}/>{t.freeRemaining}: <strong>{freeRemaining}</strong></div>}<div className="messages">{chat.map((item, index) => <div key={index} className={`message-wrap ${item.from.startsWith('user') ? 'user-wrap' : 'ai-wrap'}`}><div className={`bubble ${item.from}`}>{item.text}</div>{item.from.startsWith('ai') && <Sources items={item.sources}/>}</div>)}{busy && !consultPayment && <div className="message-wrap ai-wrap"><div className="bubble ai typing"><LoaderCircle className="spin" size={16}/>{t.checking}</div></div>}</div>{consultPayment && <section className="payment-card"><div className="payment-icon"><CreditCard size={24}/></div><div className="payment-head"><span className="section-kicker">KORGAN PAYMENT</span><h3>{t.paymentNeeded}</h3></div><p>{consultPayment.paidPending ? t.paidSaved : t.consultPaymentText}</p><div className="payment-amount">{money(consultPayment.amount_kzt)}</div>{!consultPayment.paidPending && <><button className="primary wide" onClick={() => window.open(consultPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadConsultReceipt}/></label></>}{consultPayment.paidPending && <button className="primary wide" disabled={busy} onClick={retryPaidConsultation}><RefreshCw size={18}/>{t.retryPaid}</button>}</section>}{notice && <div className="warning-note chat-warning"><AlertTriangle size={17}/>{notice}</div>}<div className="composer"><input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} disabled={Boolean(consultPayment)} placeholder={consultPayment ? t.paymentNeeded : t.message}/><button disabled={busy || !backendOk || Boolean(consultPayment)} onClick={sendMessage}><Send size={19}/></button></div></main><BottomNav/></div>;

  if (view === 'doc-payment') {
    const awaiting = docPayment.status === 'awaiting_admin'; const approved = docPayment.status === 'approved';
    return <div className="app-shell"><Header title={t.documentPayment} back="case"/><main className="page payment-page"><div className={`payment-stage-icon ${approved ? 'approved' : awaiting ? 'waiting' : ''}`}>{approved ? <CheckCircle2 size={38}/> : awaiting ? <Clock3 size={38}/> : <Banknote size={38}/>}</div><span className="section-kicker">KORGAN PREPAY · #{docPayment.order_id}</span><h1>{approved ? t.paymentApproved : awaiting ? t.manualCheck : t.documentPayment}</h1><p>{approved ? t.paymentApprovedText : awaiting ? t.waitingAdmin : t.documentPaymentText}</p><div className="payment-amount centered">{money(docPayment.amount_kzt)}</div><section className="analysis-card manual-card"><div className="card-head"><div><span className="section-kicker">SECURITY</span><h2>{t.manualCheck}</h2></div><ClipboardCheck size={22}/></div><p>{t.manualCheckSub}</p></section>{docPayment.decision_note && !approved && !awaiting && <div className="warning-note"><XCircle size={17}/>{t.paymentRejected}</div>}{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{!approved && !awaiting && <><button className="primary wide" onClick={() => window.open(docPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadDocReceipt}/></label></>}{awaiting && <button className="secondary wide" disabled={busy} onClick={refreshDocPayment}><RefreshCw size={18}/>{t.checkPayment}</button>}{approved && <button className="primary wide" disabled={busy} onClick={generateDocument}>{busyAction === 'generate' ? <LoaderCircle className="spin" size={18}/> : <Sparkles size={18}/>} {busyAction === 'generate' ? t.generating : t.startPaidGeneration}</button>}</main></div>;
  }

  if (view === 'generating') {
    const failed = generation.status === 'failed';
    return <div className="app-shell"><Header title={t.preparing} back="case"/><main className="page ready-page">
      <div className={`success-ring ${failed ? '' : 'preliminary-ring'}`}>{failed ? <ShieldAlert size={44}/> : <LoaderCircle className="spin" size={44}/>}</div>
      <h1>{failed ? t.preparingFailed : t.preparing}</h1>
      <p>{failed ? (generation.error || t.down) : t.preparingText}</p>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={generation.progress} aria-label={stageText(generation.stage, language)} style={{ width: '100%', height: 8, borderRadius: 99, overflow: 'hidden', background: 'rgba(255,255,255,0.12)' }}>
        <span style={{ display: 'block', height: '100%', width: `${generation.progress}%`, background: 'currentColor', transition: 'width .4s ease' }}/>
      </div>
      <div className="release-grid"><div><span>{t.status}</span><strong>{stageText(generation.stage, language)}</strong></div><div><span>{t.progress}</span><strong>{generation.progress}%</strong></div></div>
      {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
      {failed && generation.retryable && <button className="primary wide" disabled={busy} onClick={retryGeneration}>{busy ? <LoaderCircle className="spin" size={18}/> : <RefreshCw size={18}/>} {t.retryGeneration}</button>}
      <button className="secondary wide" onClick={() => go('case')}><ArrowLeft size={18}/>{t.backToCase}</button>
    </main></div>;
  }

  if (view === 'ready') { const ready = Boolean(documentResult?.filing_ready); return <div className="app-shell"><Header title={t.docReady} back="case"/><main className="page ready-page"><div className={`success-ring ${ready ? '' : 'preliminary-ring'}`}>{ready ? <CheckCircle2 size={48}/> : <ShieldAlert size={44}/>}</div><span className={`release-badge ${ready ? 'ready' : 'preliminary'}`}>{ready ? t.filingReady : t.preliminary}</span><h1>{documentResult?.title || t.docReady}</h1><p>{ready ? t.verified : t.needsCheck}</p><div className="release-grid"><div><span>{t.quality}</span><strong>{typeof documentResult?.quality_score === 'number' ? `${documentResult.quality_score}/10` : '—'}</strong></div><div><span>{t.check}</span><strong>{ready ? t.filingReady : t.preliminary}</strong></div></div>{documentResult?.todo_before_filing?.length > 0 && <div className="warning-note left-note"><AlertTriangle size={17}/><span>{documentResult.todo_before_filing.join(' · ')}</span></div>}<div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="primary wide" disabled={!activeCase || busy} onClick={deliverActiveDocument}>{busy ? <LoaderCircle className="spin" size={18}/> : <Download size={18}/>} {t.download}</button><button className="lawyer-btn wide" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button></main></div>; }

  if (view === 'cases') return <div className="app-shell"><Header title={t.myCases}/><main className="page"><ConnectionBanner/>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{cases.length === 0 && <section className="analysis-card empty-card"><FolderOpen size={30}/><h2>{t.noCases}</h2><p>{t.noCasesSub}</p></section>}{cases.map(item => { const [title] = docText(item.document_type, language); return <button className="case-list-item" key={item.id} onClick={() => openCase(item)}><div className="case-badge"><Scale size={20}/></div><div><strong>{item.title || title}</strong><small>{item.id} · {item.materials_count || 0} файл(ов){item.has_document ? ' · DOCX' : ''}</small></div><ChevronRight size={18}/></button>; })}<button className="primary wide" onClick={() => go('documents')}>{t.createNew}</button></main><BottomNav/></div>;

  if (view === 'admin-payments') return <div className="app-shell"><Header title={t.adminTitle} back="profile"/><main className="page admin-page">{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="secondary wide" disabled={adminBusy} onClick={loadAdminOrders}>{adminBusy ? <LoaderCircle className="spin" size={18}/> : <RefreshCw size={18}/>} {t.adminRefresh}</button>{!adminBusy && adminOrders.length === 0 && <section className="analysis-card empty-card"><ClipboardCheck size={30}/><h2>{t.adminEmpty}</h2></section>}{adminOrders.map(order => { const check = order.receipt_check || {}; return <section className="analysis-card admin-order" key={order.order_id}><div className="card-head"><div><span className="section-kicker">{t.order} #{order.order_id}</span><h2>{docText(order.document_type, language)[0]}</h2></div><strong className="admin-amount">{money(order.amount_kzt)}</strong></div><div className="fact"><span>{t.clientRef}</span><strong>{order.client_ref}</strong></div><div className="fact"><span>Case</span><strong>{order.case_id}</strong></div><div className="fact"><span>{t.payer}</span><strong>{check.payer || '—'}</strong></div><div className="fact"><span>{t.recipient}</span><strong>{check.merchant_or_recipient || '—'}</strong></div><div className="fact"><span>{t.dateTime}</span><strong>{check.date_time || '—'}</strong></div><div className="fact"><span>{t.transaction}</span><strong>{order.transaction_id || check.receipt_or_transaction_id || '—'}</strong></div>{check.suspicious_signals?.length > 0 && <div className="warning-note"><AlertTriangle size={17}/><span>{t.anomalies}: {check.suspicious_signals.join(' · ')}</span></div>}<div className="admin-actions"><button className="secondary danger" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, false)}><XCircle size={17}/>{t.reject}</button><button className="primary" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, true)}><CheckCircle2 size={17}/>{t.approve}</button></div></section>; })}</main></div>;

  if (view === 'help') return <div className="app-shell"><Header title={t.help}/><main className="page"><ConnectionBanner/><section className="analysis-card"><div className="card-head"><div><span className="section-kicker">KORGAN Legal AI</span><h2>{t.help}</h2></div><CircleHelp size={22}/></div><p>{t.helpText}</p></section><button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button></main><BottomNav/></div>;

  if (view === 'profile') return <div className="app-shell"><Header title={t.profile}/><main className="page"><ConnectionBanner/><section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>{telegramUser?.firstName || 'KORGAN'}</h2><p>{telegramUser?.username ? `@${telegramUser.username}` : 'Telegram Mini App'}</p></div><span className={`profile-state ${backendOk ? 'ok' : 'down'}`}>{backendOk ? <BadgeCheck size={16}/> : <WifiOff size={16}/>}</span></section><section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>{t.language}</strong><small>Русский / Қазақша</small></div><div className="language-switch compact"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div></div></section>{pricing && <section className="analysis-card pricing-card"><div className="card-head"><div><span className="section-kicker">KORGAN</span><h2>{t.pricing}</h2></div><CreditCard size={22}/></div><div className="fact"><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div>{pricing.consultation_limit_enabled && <div className="fact"><span>{t.consultPrice}</span><strong>{money(pricing.consultation_price_kzt)}</strong></div>}{pricing.document_payments_enabled && <div className="fact"><span>{t.docPrice}</span><strong>{money(pricing.document_price_kzt)}</strong></div>}</section>}{pricing?.is_admin && <button className="primary wide admin-entry" onClick={openAdmin}><ClipboardCheck size={18}/>{t.admin}</button>}<section className="analysis-card system-card"><div className="card-head"><div><span className="section-kicker">SYSTEM</span><h2>{backendOk ? t.systemReady : t.systemProblem}</h2></div>{backendOk ? <BadgeCheck size={22}/> : <WifiOff size={22}/>}</div><div className="fact"><span>{t.runtime}</span><strong>{runtimeInfo?.parity?.service_outer || '—'}</strong></div><div className="fact"><span>{t.quality}</span><strong>{runtimeInfo?.word_quality_target || '—'}</strong></div><div className="fact"><span>{t.secure}</span><strong>AES-256-GCM</strong></div>{pricing?.document_payments_enabled && <div className="fact"><span>{t.manualCheck}</span><strong>{runtimeInfo?.parity?.document_manual_confirmation ? 'ON' : 'OFF'}</strong></div>}<button className="secondary wide compact-action" onClick={boot}><RefreshCw size={17}/>{t.refresh}</button></section><section className="privacy-card static"><LockKeyhole size={20}/><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div></section><button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button><button className="secondary wide danger" disabled={busy} onClick={deleteAllData}><Trash2 size={18}/>{t.deleteAll}</button></main><BottomNav/></div>;

  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div><div className={`top-status ${connection}`}><span/>{connection === 'ok' ? t.connected : connection === 'down' ? t.down : t.connecting}</div></header><main className="home-page"><ConnectionBanner/><section className="hero"><div className="hero-copy"><div className="online"><span className={backendOk ? 'online-dot' : 'offline-dot'}/>{backendOk ? t.systemReady : connection === 'checking' ? t.connecting : t.systemProblem}</div><h1>{t.heroTitle}</h1><p>{t.heroText}</p><button disabled={!backendOk} onClick={() => go('chat')}>{t.startConsult}<ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>{pricing && <section className="quick-stats"><div><MessageCircle size={17}/><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div><div><FileText size={17}/><span>{t.docPrice}</span><strong>{pricing.document_payments_enabled ? money(pricing.document_price_kzt) : '—'}</strong></div></section>}<section className="action-grid"><button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>{t.consultation}</h2><p>{t.consultationSub}</p></button><button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><h2>{t.prepare}</h2><p>{t.prepareSub}</p></button><button className="action-card" onClick={() => { go('cases'); refreshCases().catch(() => {}); }}><div className="action-icon case"><FolderOpen/></div><h2>{t.myCases}</h2><p>{t.casesSub}</p></button><button className="action-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><h2>{t.privacy}</h2><p>{t.privacySub}</p></button><PersonalLawyerCard language={language}/></section><section className="privacy-card" onClick={() => go('profile')}><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div><ChevronRight size={18}/></section></main><BottomNav/></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
