import React, { useEffect, useMemo, useState } from 'react';
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
  loadState, saveDraft, setLanguage as persistLanguage, acceptConsent,
  clearLocalCaseData, clearAllLocalData
} from './store';
import { getTelegramUser, initTelegram, haptic } from './telegram';

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
    selectDoc: 'Выбор документа', searchDoc: 'Поиск документа', documents: 'Документы', docPrice: 'Подготовка документа',
    newCase: 'Новое дело', tell: 'Расскажите, что произошло', tellSub: 'Опишите ситуацию или сразу загрузите PDF, DOCX, TXT либо фотографии. Все материалы будут привязаны к одному делу.',
    placeholder: 'Стороны, отношения/договор, даты, суммы, нарушение, доказательства, позиция и желаемый результат…', create: 'Создать дело', creating: 'Создаю дело…',
    addFile: 'Загрузить документы / фото', processing: 'Обрабатываю материалы…', selected: 'Выбрано', materials: 'Материалы дела', files: 'Файлов',
    consultCase: 'Консультация по делу', generate: 'Подготовить документ', generating: 'Проверяю право и формирую Word…', deleteCase: 'Удалить дело',
    caseCreated: 'Дело создано', materialsLoaded: 'Материалы загружены', docReady: 'Документ готов', noCases: 'Дел пока нет', noCasesSub: 'Создайте первое дело и добавьте факты или документы.', createNew: 'Создать новое дело',
    download: 'Скачать DOCX', downloadExisting: 'Скачать готовый DOCX', sendToTelegram: 'Прислать в Telegram', sending: 'Отправляю…', sentToTelegram: 'Документ отправлен вам в чат с ботом KORGAN.', liveReview: 'Проверка живым юристом',
    message: 'Напишите юридический вопрос…', checking: 'Проверяю право и источники…', sources: 'Источники', freeRemaining: 'Бесплатных консультаций осталось',
    paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите консультацию через Kaspi. Затем отсканируйте QR именно на фискальном чеке и вставьте ссылку receipt.kaspi.kz — KORGAN проверит оплату автоматически.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек (резерв)', checkingReceipt: 'Проверяю оплату…', retryPaid: 'Повторить ответ без новой оплаты', paidSaved: 'Оплата сохранена. Повторно платить не нужно.',
    receiptUrlPlaceholder: 'https://receipt.kaspi.kz/...', verifyPayment: 'Проверить оплату',
    documentPayment: 'Оплата документа', documentPaymentText: 'Оплатите документ через Kaspi. Затем отсканируйте QR на фискальном чеке и вставьте ссылку receipt.kaspi.kz. После проверки KORGAN сразу начнёт подготовку Word-документа.',
    waitingAdmin: 'Для старой платёжной заявки нужна повторная проверка того же фискального QR. Повторно платить не нужно.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Оплата сохранена. Если предыдущая генерация прервалась, документ можно подготовить повторно без новой оплаты.', checkPayment: 'Обновить статус', startPaidGeneration: 'Повторить подготовку без оплаты',
    paymentRejected: 'Оплата не подтверждена. Проверьте фискальный QR и данные платежа.', manualCheck: 'Проверка Kaspi ОФД', manualCheckSub: 'KORGAN проверяет фискальный чек по receipt.kaspi.kz: сумму, получателя, время и уникальность. Решение AI по картинке не используется.',
    filingReady: 'Готов к подаче', preliminary: 'Предварительный документ', verified: 'Проверки пройдены', needsCheck: 'Требуется проверка', quality: 'Качество', status: 'Статус', check: 'Проверка',
    pricing: 'Тарифы и лимиты', freePerDay: 'Бесплатных консультаций в день', consultPrice: 'Консультация после лимита', language: 'Язык', deleteAll: 'Удалить все мои данные',
    dataControl: 'Данные под контролем', dataControlSub: 'Mini App использует отдельный API и не изменяет production Telegram‑агента.', runtime: 'Юридическое ядро', secure: 'Защищённое хранение', refresh: 'Обновить', support: 'Техподдержка',
    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документов KORGAN использует то же production‑юридическое ядро, а оплату подтверждает через Kaspi ОФД по фискальному QR. После подтверждения документ запускается автоматически.',
    admin: 'Проверка оплат', adminTitle: 'Оплаты документов', adminEmpty: 'Чеков на ручную проверку нет', approve: 'Подтвердить', reject: 'Отклонить', adminRefresh: 'Обновить список', payer: 'Плательщик', recipient: 'Получатель', transaction: 'Операция', dateTime: 'Дата / время', anomalies: 'Аномалии AI', clientRef: 'Клиент', order: 'Заказ',
  },
  kk: {
    home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль', help: 'Көмек',
    consentTitle: 'KORGAN Legal AI пайдалану шарттары', consentText: 'KORGAN — Қазақстан Республикасының құқығына арналған жасанды интеллект жүйесі. Жауаптар мен құжаттар пайдаланушы деректері және тексерілетін дереккөздер бойынша жасалады. Құжатты бергенге дейін дербес деректерді, сомаларды, дәлелдемелерді, соттылықты және мемлекеттік бажды тексеріңіз.', privacyText: 'Материалдар тек кеңес беру және құжат дайындау үшін пайдаланылады. Mini App деректерін профильден жоюға болады.', accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын',
    heroTitle: 'Кәсіби AI-заңгер', heroText: 'Кеңес, материалдарды талдау, құжаттар және сапаны бақылау бір жұмыс кеңістігінде.', startConsult: 'Кеңесті бастау', consultation: 'Кеңес', consultationSub: 'Дереккөздерді тексеретін құқықтық талдау', prepare: 'Құжат дайындау', prepareSub: 'KORGAN production Word-құжаттары', myCases: 'Менің істерім', casesSub: 'Материалдар, кеңестер және дайын құжаттар', privacy: 'Құпиялылық', privacySub: 'Келісім, тіл және деректерді басқару', connected: 'KORGAN қосылды', connecting: 'Қосылым тексерілуде…', down: 'Қызмет уақытша қолжетімсіз', systemReady: 'Жүйе дайын', systemProblem: 'Қосылым мәселесі', retry: 'Қайталау',
    selectDoc: 'Құжатты таңдау', searchDoc: 'Құжатты іздеу', documents: 'Құжаттар', docPrice: 'Құжат дайындау', newCase: 'Жаңа іс', tell: 'Не болғанын жазыңыз', tellSub: 'Жағдайды сипаттаңыз немесе PDF, DOCX, TXT не фотосуреттерді бірден жүктеңіз. Барлық материал бір іске бекітіледі.', placeholder: 'Тараптар, қатынас/шарт, күндер, сомалар, бұзушылық, дәлелдер, ұстаным және қажетті нәтиже…', create: 'Іс құру', creating: 'Іс құрылуда…', addFile: 'Құжаттар / фото жүктеу', processing: 'Материалдар өңделуде…', selected: 'Таңдалды', materials: 'Іс материалдары', files: 'Файлдар', consultCase: 'Іс бойынша кеңес', generate: 'Құжат дайындау', generating: 'Құқық тексеріліп, Word жасалуда…', deleteCase: 'Істі жою', caseCreated: 'Іс құрылды', materialsLoaded: 'Материалдар жүктелді', docReady: 'Құжат дайын', noCases: 'Әзірге іс жоқ', noCasesSub: 'Бірінші істі құрып, фактілер немесе құжаттар қосыңыз.', createNew: 'Жаңа іс құру', download: 'DOCX жүктеу', downloadExisting: 'Дайын DOCX жүктеу', sendToTelegram: 'Telegram-ға жіберу', sending: 'Жіберілуде…', sentToTelegram: 'Құжат KORGAN ботындағы чатқа жіберілді.', liveReview: 'Тірі заңгердің тексеруі',
    message: 'Заңдық сұрағыңызды жазыңыз…', checking: 'Құқық пен дереккөздер тексерілуде…', sources: 'Дереккөздер', freeRemaining: 'Қалған тегін кеңес', paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Kaspi арқылы кеңес ақысын төлеңіз. Содан кейін фискалдық чектегі QR-кодты сканерлеп, receipt.kaspi.kz сілтемесін енгізіңіз — KORGAN төлемді автоматты тексереді.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу (резерв)', checkingReceipt: 'Төлем тексерілуде…', retryPaid: 'Жаңа төлемсіз жауапты қайталау', paidSaved: 'Төлем сақталды. Қайта төлеу қажет емес.', receiptUrlPlaceholder: 'https://receipt.kaspi.kz/...', verifyPayment: 'Төлемді тексеру',
    documentPayment: 'Құжат төлемі', documentPaymentText: 'Kaspi арқылы құжат үшін төлеңіз. Содан кейін фискалдық чектегі QR-кодты сканерлеп, receipt.kaspi.kz сілтемесін енгізіңіз. Тексеруден кейін KORGAN Word-құжатын бірден дайындай бастайды.', waitingAdmin: 'Ескі төлем өтінімі үшін сол фискалдық QR-ды қайта тексеру қажет. Қайта төлем жасамаңыз.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Төлем сақталды. Егер генерация үзілсе, құжатты жаңа төлемсіз қайта дайындауға болады.', checkPayment: 'Мәртебені жаңарту', startPaidGeneration: 'Жаңа төлемсіз қайта дайындау', paymentRejected: 'Төлем расталмады. Фискалдық QR мен төлем деректерін тексеріңіз.', manualCheck: 'Kaspi ОФД тексеруі', manualCheckSub: 'KORGAN receipt.kaspi.kz арқылы соманы, алушыны, уақытты және чектің бірегейлігін тексереді. Сурет бойынша AI шешімі қолданылмайды.', filingReady: 'Беруге дайын', preliminary: 'Алдын ала құжат', verified: 'Тексерулер өтті', needsCheck: 'Тексеру қажет', quality: 'Сапа', status: 'Мәртебе', check: 'Тексеру', pricing: 'Тарифтер мен лимиттер', freePerDay: 'Күніне тегін кеңес', consultPrice: 'Лимиттен кейінгі кеңес', language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', runtime: 'Заңдық ядро', secure: 'Қорғалған сақтау', refresh: 'Жаңарту', support: 'Техқолдау', helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжаттар үшін KORGAN AI‑агентпен бірдей production заңдық ядроны қолданады, ал төлем Kaspi ОФД арқылы фискалдық QR бойынша тексеріледі. Расталғаннан кейін құжат автоматты түрде іске қосылады.',
    admin: 'Төлемдерді тексеру', adminTitle: 'Құжат төлемдері', adminEmpty: 'Қолмен тексерілетін чек жоқ', approve: 'Растау', reject: 'Қабылдамау', adminRefresh: 'Тізімді жаңарту', payer: 'Төлеуші', recipient: 'Алушы', transaction: 'Операция', dateTime: 'Күні / уақыты', anomalies: 'AI аномалиялары', clientRef: 'Клиент', order: 'Тапсырыс',
  },
};

const money = value => `${Number(value || 0).toLocaleString('ru-RU')} ₸`;
const docText = (id, lang) => DOCUMENTS.find(x => x.id === id)?.[lang] || ['KORGAN Legal AI', ''];
const safeUrl = value => /^https?:\/\//i.test(String(value || '').trim()) ? String(value).trim() : '';
const sourceLabel = value => { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return String(value || ''); } };
const isKaspiReceiptUrl = value => /^https:\/\/receipt\.kaspi\.kz(?:\/|$)/i.test(String(value || '').trim());

function downloadBase64(base64, filename) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
  const a = document.createElement('a');
  a.href = url; a.download = filename || 'KORGAN_document.docx'; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function App() {
  const initial = loadState();
  const [screen, setScreen] = useState('home');
  const [language, setLanguage] = useState(initial.language || 'ru');
  const [consent, setConsent] = useState(Boolean(initial.consentAccepted));
  const [connection, setConnection] = useState('checking');
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [pricing, setPricing] = useState(null);
  const [telegramUser, setTelegramUser] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
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
  const [consultReceiptUrl, setConsultReceiptUrl] = useState('');
  const [receiptBusy, setReceiptBusy] = useState(false);
  const [documentResult, setDocumentResult] = useState(null);
  const [docPayment, setDocPayment] = useState(null);
  const [docReceiptUrl, setDocReceiptUrl] = useState('');
  const [adminOrders, setAdminOrders] = useState([]);
  const [adminBusy, setAdminBusy] = useState(false);
  const t = L[language];
  const backendOk = connection === 'ok';

  const resetChat = () => {
    setConsultPayment(null); setConsultReceiptUrl('');
    setChat([{ from: 'ai', text: language === 'kk' ? 'Заңдық сұрағыңызды жазыңыз. Мен Қазақстан Республикасының құқығын және дереккөздерді тексеремін.' : 'Опишите юридический вопрос. Я проверю право Республики Казахстан и источники.' }]);
  };

  const boot = async () => {
    if (!consent || !isBackendConnected()) { setConnection('down'); return; }
    setConnection('checking'); setNotice('');
    try {
      const health = await korganApi.health();
      await korganApi.acceptConsent(TERMS_VERSION);
      const [caseResult, priceResult] = await Promise.all([korganApi.listCases(), korganApi.pricing()]);
      setRuntimeInfo(health); setPricing(priceResult); setCases(caseResult.cases || []); setConnection('ok');
    } catch (error) { setConnection('down'); setNotice(error?.message || t.down); }
  };

  useEffect(() => { initTelegram(); setTelegramUser(getTelegramUser()); }, []);
  useEffect(() => { if (!activeCase) resetChat(); }, [language]);
  useEffect(() => { if (consent) boot(); }, [consent]);
  useEffect(() => {
    if (screen !== 'doc-payment' || docPayment?.status !== 'awaiting_admin' || !docPayment?.order_id) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const result = await korganApi.documentPaymentStatus(docPayment.order_id);
        if (result?.payment) setDocPayment(result.payment);
      } catch {}
    }, 8000);
    return () => window.clearInterval(timer);
  }, [screen, docPayment?.status, docPayment?.order_id]);

  const filteredDocuments = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? DOCUMENTS.filter(item => item[language].join(' ').toLowerCase().includes(q)) : DOCUMENTS;
  }, [query, language]);

  const go = next => { haptic(); setNotice(''); setScreen(next); };
  const switchLanguage = next => { setLanguage(next); persistLanguage(next); };
  const refreshCases = async () => { const result = await korganApi.listCases(); setCases(result.cases || []); return result.cases || []; };

  const acceptTerms = async () => {
    setBusy(true); setNotice('');
    try { await korganApi.acceptConsent(TERMS_VERSION); acceptConsent(TERMS_VERSION); setConsent(true); }
    catch (error) { setNotice(error?.message || t.down); }
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
      setActiveCase(item); setDocumentResult(null); setDocPayment(null); setDocReceiptUrl(''); resetChat(); await refreshCases(); clearLocalCaseData(); setCaseText(''); setPendingFiles([]); setScreen('case');
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const openCase = async item => {
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getCase(item.id); const detail = result.case; setActiveCase(detail); setDocumentResult(null); setDocPayment(null); setDocReceiptUrl(''); setConsultPayment(null); setConsultReceiptUrl('');
      const restored = (detail.conversation || []).map(entry => ({ from: entry.role === 'user' ? 'user' : 'ai', text: entry.text || '', sources: entry.sources || [] }));
      setChat(restored.length ? restored : [{ from: 'ai', text: language === 'kk' ? 'Осы іс бойынша сұрағыңызды жазыңыз.' : 'Задайте вопрос по этому делу.' }]); setScreen('case');
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const uploadMaterial = async event => {
    const files = Array.from(event.target.files || []); event.target.value = '';
    if (!files.length || !activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      let latest = activeCase;
      await korganApi.uploadMaterials(activeCase.id, files, ({ result }) => { latest = result.case || latest; setActiveCase(latest); });
      setActiveCase(latest); setDocPayment(null); setDocReceiptUrl(''); await refreshCases(); setNotice(language === 'kk' ? `${files.length} файл өңделді.` : `Обработано файлов: ${files.length}.`);
    } catch (error) { setNotice(error?.message || t.down); }
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
      if (result.payment_required && result.payment) { setFreeRemaining(0); setConsultReceiptUrl(''); setConsultPayment({ ...result.payment, paidPending: false }); }
      else appendAnswer(result);
    } catch (error) { setChat(prev => [...prev, { from: 'ai error', text: error?.message || t.down }]); }
    finally { setBusy(false); }
  };
  const submitConsultReceiptUrl = async () => {
    if (!consultPayment?.order_id || receiptBusy || !isKaspiReceiptUrl(consultReceiptUrl)) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.submitConsultationReceiptUrl(consultPayment.order_id, consultReceiptUrl); appendAnswer(result); setConsultPayment(null); setConsultReceiptUrl(''); }
    catch (error) { setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };
  const uploadConsultReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !consultPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, file); appendAnswer(result); setConsultPayment(null); setConsultReceiptUrl(''); }
    catch (error) { if (error?.status === 503) { setConsultPayment(prev => ({ ...prev, paidPending: true })); setNotice(t.paidSaved); } else setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };
  const retryPaidConsultation = async () => {
    if (!consultPayment?.order_id || busy) return; setBusy(true); setNotice('');
    try { const result = await korganApi.retryPaidConsultation(consultPayment.order_id); appendAnswer(result); setConsultPayment(null); setConsultReceiptUrl(''); }
    catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };

  const applyDocumentResult = async result => {
    setDocumentResult(result); setDocPayment(null); setDocReceiptUrl('');
    setActiveCase(prev => prev ? ({ ...prev, status: result.status, title: result.title, verification_status: result.verification_status, has_document: true, filing_ready: result.filing_ready, release_status: result.release_status, quality_score: result.quality_score }) : prev);
    await refreshCases(); setScreen('ready');
  };
  const generateDocument = async () => {
    if (!activeCase || busy) return; setBusy(true); setNotice('');
    try {
      const result = await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language);
      if (result?.payment_required && result?.payment) { setDocPayment(result.payment); setDocReceiptUrl(''); setScreen('doc-payment'); return; }
      await applyDocumentResult(result);
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };
  const submitDocReceiptUrl = async () => {
    if (!docPayment?.order_id || receiptBusy || !isKaspiReceiptUrl(docReceiptUrl)) return;
    setReceiptBusy(true); setNotice('');
    try {
      const result = await korganApi.submitDocumentReceiptUrl(docPayment.order_id, docReceiptUrl);
      if (result?.document_base64) await applyDocumentResult(result);
      else if (result?.payment) { setDocPayment(result.payment); setNotice(result.message || t.paymentApproved); }
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };
  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try {
      const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file);
      if (result?.document_base64) await applyDocumentResult(result);
      else if (result?.payment) { setDocPayment(result.payment); setNotice(result.message || t.paymentApproved); }
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };
  const refreshDocPayment = async () => {
    if (!docPayment?.order_id) return; setBusy(true); setNotice('');
    try { const result = await korganApi.documentPaymentStatus(docPayment.order_id); setDocPayment(result.payment); }
    catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };
  const retryPaidDocument = async () => {
    if (!docPayment?.order_id || busy) return; setBusy(true); setNotice('');
    try { await applyDocumentResult(await korganApi.retryPaidDocument(docPayment.order_id)); }
    catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };
  const downloadExisting = async () => {
    if (!activeCase || busy) return; setBusy(true); setNotice('');
    try { const result = await korganApi.getDocument(activeCase.id); setDocumentResult(result); downloadBase64(result.document_base64, result.filename); }
    catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };

  // Встроенный браузер Telegram блокирует сохранение файла через blob и
  // <a download>: клик проходит, файла нет, ошибки тоже нет. Поэтому основной
  // способ получить документ в мини-аппе — попросить бота прислать его в чат.
  const sendToTelegram = async () => {
    if (!activeCase) return;
    setBusy(true);
    try {
      const result = await korganApi.sendDocumentToTelegram(activeCase.id);
      setNotice(result?.message || t.sentToTelegram);
    } catch (error) {
      setNotice(error?.payload?.detail || error?.message || t.down);
    } finally {
      setBusy(false);
    }
  };

  const deleteCurrentCase = async () => {
    if (!activeCase || !window.confirm(language === 'kk' ? 'Бұл істі жою керек пе?' : 'Удалить это дело и все его данные?')) return;
    setBusy(true); try { await korganApi.deleteCase(activeCase.id); setActiveCase(null); setDocPayment(null); setDocReceiptUrl(''); await refreshCases(); setScreen('cases'); } catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };
  const deleteAllData = async () => {
    if (!window.confirm(language === 'kk' ? 'Барлық Mini App деректерін жою керек пе?' : 'Удалить все данные Mini App и все дела?')) return;
    setBusy(true); try { await korganApi.deleteMyData(); clearAllLocalData(); setCases([]); setActiveCase(null); setConsent(false); setScreen('home'); } catch (error) { setNotice(error?.message || t.down); } finally { setBusy(false); }
  };

  const loadAdminOrders = async () => {
    setAdminBusy(true); setNotice('');
    try { const result = await korganApi.adminDocumentPayments('awaiting_admin'); setAdminOrders(result.orders || []); }
    catch (error) { setNotice(error?.message || t.down); } finally { setAdminBusy(false); }
  };
  const openAdmin = async () => { setScreen('admin-payments'); await loadAdminOrders(); };
  const decideAdminOrder = async (orderId, approved) => {
    const question = approved ? (language === 'kk' ? 'Kaspi Pay тарихында осы төлем нақты расталды ма?' : 'Вы действительно сверили этот платёж в истории Kaspi Pay?') : (language === 'kk' ? 'Бұл төлемді қабылдамау керек пе?' : 'Отклонить эту оплату?');
    if (!window.confirm(question)) return;
    setAdminBusy(true); setNotice('');
    try { await korganApi.adminDocumentPaymentDecision(orderId, approved, approved ? 'Kaspi Pay manually confirmed' : 'Payment not confirmed in Kaspi Pay'); await loadAdminOrders(); }
    catch (error) { setNotice(error?.message || t.down); } finally { setAdminBusy(false); }
  };

  const Header = ({ title, back = 'home' }) => <header className="subbar"><button className="icon-btn" onClick={() => go(back)}><ArrowLeft size={20}/></button><strong>{title}</strong><span className="header-spacer"/></header>;
  const BottomNav = () => <nav className="bottom-nav">
    <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>
    <button className={screen === 'cases' ? 'active' : ''} onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><FolderOpen size={20}/><span>{t.cases}</span></button>
    <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>
    <button className={screen === 'help' ? 'active' : ''} onClick={() => go('help')}><CircleHelp size={20}/><span>{t.help}</span></button>
    <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>
  </nav>;
  const ConnectionBanner = () => connection === 'down' ? <div className="connection-banner error-banner"><WifiOff size={18}/><div><strong>{t.systemProblem}</strong><small>{t.down}</small></div><button onClick={boot}><RefreshCw size={17}/>{t.retry}</button></div> : null;
  const Sources = ({ items = [] }) => !items.length ? null : <div className="source-list"><span>{t.sources}</span>{items.map((source, i) => { const url = safeUrl(source); return url ? <a key={`${source}-${i}`} href={url} target="_blank" rel="noreferrer"><Link2 size={13}/>{sourceLabel(url)}<ExternalLink size={12}/></a> : <span className="source-chip" key={`${source}-${i}`}><Link2 size={13}/>{source}</span>; })}</div>;

  if (!consent) return <div className="app-shell consent-shell"><main className="page consent-page">
    <div className="brand-mark large"><Scale size={28}/></div><div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div>
    <h1>{t.consentTitle}</h1><section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section><section className="privacy-card static"><LockKeyhole size={22}/><div><strong>{t.privacy}</strong><p>{t.privacyText}</p></div></section>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="primary wide" disabled={busy} onClick={acceptTerms}>{busy ? <LoaderCircle className="spin" size={18}/> : <ShieldCheck size={18}/>} {t.accept}</button><button className="secondary wide" onClick={declineTerms}>{t.decline}</button><small>v. {TERMS_VERSION}</small>
  </main></div>;

  if (screen === 'documents') return <div className="app-shell"><Header title={t.selectDoc}/><main className="page"><ConnectionBanner/><div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t.searchDoc}/></div>{pricing?.document_payments_enabled && <div className="price-note"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · Kaspi</span></div>}<div className="section-kicker list-kicker">{t.documents}</div><div className="list-card">{filteredDocuments.map(item => { const [title, subtitle] = item[language]; const Icon = item.icon; return <button className="list-row" key={item.id} onClick={() => chooseDocument(item.id)}><span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/></button>; })}</div></main><BottomNav/></div>;

  if (screen === 'new-case') { const [title] = docText(selectedDocument, language); return <div className="app-shell"><Header title={t.newCase} back="documents"/><main className="page creation-page"><ConnectionBanner/><div className="big-title"><span className="eyebrow">{title}</span><h1>{t.tell}</h1><p>{t.tellSub}</p></div><textarea className="case-input" value={caseText} onChange={e => saveCaseText(e.target.value)} maxLength={8000} placeholder={t.placeholder}/><div className="input-meta"><Sparkles size={17}/><span>{caseText.length}/8000</span></div><label className="secondary wide"><Paperclip size={18}/>{t.addFile}<input className="hidden-input" multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={chooseInitialFiles}/></label>{pendingFiles.length > 0 && <div className="success-note">{t.selected}: {pendingFiles.map(f => f.name).join(', ')}</div>}{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="primary wide" disabled={(!caseText.trim() && !pendingFiles.length) || busy || !backendOk} onClick={createCase}>{busy ? <LoaderCircle className="spin" size={18}/> : <ArrowRight size={18}/>} {busy ? t.creating : t.create}</button></main></div>; }

  if (screen === 'case') {
    if (!activeCase) return <div className="app-shell"><Header title={t.cases} back="cases"/><main className="page"><p>{t.noCases}</p></main><BottomNav/></div>;
    const [title] = docText(activeCase.document_type, language); const statusText = activeCase.status === 'document_ready' ? t.docReady : activeCase.status === 'materials_ready' ? t.materialsLoaded : t.caseCreated;
    return <div className="app-shell"><Header title={activeCase.id} back="cases"/><main className="page"><ConnectionBanner/><section className="status-card"><div><span className="section-kicker">{t.status}</span><h2>{statusText}</h2></div><span className="pill success">{(activeCase.language || language).toUpperCase()}</span></section><section className="analysis-card"><div className="card-head"><div><span className="section-kicker">{t.materials}</span><h2>{activeCase.title || title}</h2></div><Sparkles size={22}/></div>{activeCase.description && <p className="case-description">{activeCase.description}</p>}<div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count || 0}</strong></div>{activeCase.material_names?.length > 0 && <div className="material-list">{activeCase.material_names.map(name => <span key={name}><Paperclip size={13}/>{name}</span>)}</div>}{activeCase.verification_status && <div className="fact"><span>{t.check}</span><strong>{activeCase.filing_ready ? t.verified : t.needsCheck}</strong></div>}{typeof activeCase.quality_score === 'number' && <div className="fact"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}</section>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<label className="secondary wide"><Paperclip size={18}/>{busy ? t.processing : t.addFile}<input className="hidden-input" disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterial}/></label><button className="secondary wide" onClick={() => go('chat')}><MessageCircle size={18}/>{t.consultCase}</button>{activeCase.has_document && <button className="primary wide" disabled={busy} onClick={sendToTelegram}><Send size={18}/>{busy ? t.sending : t.sendToTelegram}</button>}{activeCase.has_document && <button className="secondary wide" disabled={busy} onClick={downloadExisting}><Download size={18}/>{t.downloadExisting}</button>}<button className="primary wide" disabled={busy || !backendOk} onClick={generateDocument}>{busy ? <LoaderCircle className="spin" size={18}/> : <FileText size={18}/>} {busy ? t.generating : pricing?.document_payments_enabled ? `${t.generate} · ${money(pricing.document_price_kzt)}` : t.generate}</button><button className="secondary wide danger" disabled={busy} onClick={deleteCurrentCase}><Trash2 size={18}/>{t.deleteCase}</button></main><BottomNav/></div>;
  }

  if (screen === 'chat') return <div className="app-shell chat-shell"><Header title={activeCase ? `${t.lawyer} · ${activeCase.id}` : t.lawyer}/><main className="chat-page"><div className={`connection-note ${backendOk ? '' : 'offline'}`}><span className={backendOk ? 'dot on' : 'dot'}/>{connection === 'checking' ? t.connecting : backendOk ? t.connected : t.down}</div>{freeRemaining !== null && <div className="quota-note"><BadgeCheck size={15}/>{t.freeRemaining}: <strong>{freeRemaining}</strong></div>}<div className="messages">{chat.map((item, index) => <div key={index} className={`message-wrap ${item.from.startsWith('user') ? 'user-wrap' : 'ai-wrap'}`}><div className={`bubble ${item.from}`}>{item.text}</div>{item.from.startsWith('ai') && <Sources items={item.sources}/>}</div>)}{busy && !consultPayment && <div className="message-wrap ai-wrap"><div className="bubble ai typing"><LoaderCircle className="spin" size={16}/>{t.checking}</div></div>}</div>{consultPayment && <section className="payment-card"><div className="payment-icon"><CreditCard size={24}/></div><div className="payment-head"><span className="section-kicker">KORGAN PAYMENT</span><h3>{t.paymentNeeded}</h3></div><p>{consultPayment.paidPending ? t.paidSaved : t.consultPaymentText}</p><div className="payment-amount">{money(consultPayment.amount_kzt)}</div>{!consultPayment.paidPending && <><button className="primary wide" onClick={() => window.open(consultPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><input className="case-input" value={consultReceiptUrl} onChange={e => setConsultReceiptUrl(e.target.value)} placeholder={t.receiptUrlPlaceholder}/><button className="primary wide" disabled={receiptBusy || !isKaspiReceiptUrl(consultReceiptUrl)} onClick={submitConsultReceiptUrl}>{receiptBusy ? <LoaderCircle className="spin" size={18}/> : <ShieldCheck size={18}/>} {receiptBusy ? t.checkingReceipt : t.verifyPayment}</button><label className="secondary wide receipt-upload"><Paperclip size={18}/>{t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadConsultReceipt}/></label></>}{consultPayment.paidPending && <button className="primary wide" disabled={busy} onClick={retryPaidConsultation}><RefreshCw size={18}/>{t.retryPaid}</button>}</section>}{notice && <div className="warning-note chat-warning"><AlertTriangle size={17}/>{notice}</div>}<div className="composer"><input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} disabled={Boolean(consultPayment)} placeholder={consultPayment ? t.paymentNeeded : t.message}/><button disabled={busy || !backendOk || Boolean(consultPayment)} onClick={sendMessage}><Send size={19}/></button></div></main><BottomNav/></div>;

  if (screen === 'doc-payment' && docPayment) {
    const awaiting = docPayment.status === 'awaiting_admin'; const approved = docPayment.status === 'approved';
    return <div className="app-shell"><Header title={t.documentPayment} back="case"/><main className="page payment-page"><div className={`payment-stage-icon ${approved ? 'approved' : awaiting ? 'waiting' : ''}`}>{approved ? <CheckCircle2 size={38}/> : awaiting ? <Clock3 size={38}/> : <Banknote size={38}/>}</div><span className="section-kicker">KORGAN PAYMENT · #{docPayment.order_id}</span><h1>{approved ? t.paymentApproved : t.documentPayment}</h1><p>{approved ? t.paymentApprovedText : awaiting ? t.waitingAdmin : t.documentPaymentText}</p><div className="payment-amount centered">{money(docPayment.amount_kzt)}</div><section className="analysis-card manual-card"><div className="card-head"><div><span className="section-kicker">SECURITY</span><h2>{t.manualCheck}</h2></div><ShieldCheck size={22}/></div><p>{t.manualCheckSub}</p></section>{docPayment.decision_note && !approved && !awaiting && <div className="warning-note"><XCircle size={17}/>{t.paymentRejected}</div>}{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{!approved && <><button className="primary wide" onClick={() => window.open(docPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><input className="case-input" value={docReceiptUrl} onChange={e => setDocReceiptUrl(e.target.value)} placeholder={t.receiptUrlPlaceholder}/><button className="primary wide" disabled={receiptBusy || !isKaspiReceiptUrl(docReceiptUrl)} onClick={submitDocReceiptUrl}>{receiptBusy ? <LoaderCircle className="spin" size={18}/> : <ShieldCheck size={18}/>} {receiptBusy ? t.checkingReceipt : t.verifyPayment}</button><label className="secondary wide receipt-upload"><Paperclip size={18}/>{t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadDocReceipt}/></label></>}{awaiting && <button className="secondary wide" disabled={busy} onClick={refreshDocPayment}><RefreshCw size={18}/>{t.checkPayment}</button>}{approved && <button className="primary wide" disabled={busy} onClick={retryPaidDocument}>{busy ? <LoaderCircle className="spin" size={18}/> : <Sparkles size={18}/>} {busy ? t.generating : t.startPaidGeneration}</button>}</main></div>;
  }

  if (screen === 'ready') { const ready = Boolean(documentResult?.filing_ready); return <div className="app-shell"><Header title={t.docReady} back="case"/><main className="page ready-page"><div className={`success-ring ${ready ? '' : 'preliminary-ring'}`}>{ready ? <CheckCircle2 size={48}/> : <ShieldAlert size={44}/>}</div><span className={`release-badge ${ready ? 'ready' : 'preliminary'}`}>{ready ? t.filingReady : t.preliminary}</span><h1>{documentResult?.title || t.docReady}</h1><p>{ready ? t.verified : t.needsCheck}</p><div className="release-grid"><div><span>{t.quality}</span><strong>{typeof documentResult?.quality_score === 'number' ? `${documentResult.quality_score}/10` : '—'}</strong></div><div><span>{t.check}</span><strong>{documentResult?.release_status || '—'}</strong></div></div>{(documentResult?.verification_notes?.length > 0 || documentResult?.quality_issues?.length > 0) && <div className="warning-note left-note"><AlertTriangle size={17}/><span>{[...(documentResult.verification_notes || []), ...(documentResult.quality_issues || [])].filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</span></div>}<div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div><button className="primary wide" disabled={busy} onClick={sendToTelegram}><Send size={18}/>{busy ? t.sending : t.sendToTelegram}</button><button className="secondary wide" disabled={!documentResult?.document_base64} onClick={() => downloadBase64(documentResult.document_base64, documentResult.filename)}><Download size={18}/>{t.download}</button><button className="lawyer-btn wide" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button></main></div>; }

  if (screen === 'cases') return <div className="app-shell"><Header title={t.myCases}/><main className="page"><ConnectionBanner/>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{cases.length === 0 && <section className="analysis-card empty-card"><FolderOpen size={30}/><h2>{t.noCases}</h2><p>{t.noCasesSub}</p></section>}{cases.map(item => { const [title] = docText(item.document_type, language); return <button className="case-list-item" key={item.id} onClick={() => openCase(item)}><div className="case-badge"><Scale size={20}/></div><div><strong>{item.title || title}</strong><small>{item.id} · {item.materials_count || 0} файл(ов){item.has_document ? ' · DOCX' : ''}</small></div><ChevronRight size={18}/></button>; })}<button className="primary wide" onClick={() => go('documents')}>{t.createNew}</button></main><BottomNav/></div>;

  if (screen === 'admin-payments') return <div className="app-shell"><Header title={t.adminTitle} back="profile"/><main className="page admin-page">{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}<button className="secondary wide" disabled={adminBusy} onClick={loadAdminOrders}>{adminBusy ? <LoaderCircle className="spin" size={18}/> : <RefreshCw size={18}/>} {t.adminRefresh}</button>{!adminBusy && adminOrders.length === 0 && <section className="analysis-card empty-card"><ClipboardCheck size={30}/><h2>{t.adminEmpty}</h2></section>}{adminOrders.map(order => { const check = order.receipt_check || {}; return <section className="analysis-card admin-order" key={order.order_id}><div className="card-head"><div><span className="section-kicker">{t.order} #{order.order_id}</span><h2>{docText(order.document_type, language)[0]}</h2></div><strong className="admin-amount">{money(order.amount_kzt)}</strong></div><div className="fact"><span>{t.clientRef}</span><strong>{order.client_ref}</strong></div><div className="fact"><span>Case</span><strong>{order.case_id}</strong></div><div className="fact"><span>{t.payer}</span><strong>{check.payer || '—'}</strong></div><div className="fact"><span>{t.recipient}</span><strong>{check.merchant_or_recipient || '—'}</strong></div><div className="fact"><span>{t.dateTime}</span><strong>{check.date_time || '—'}</strong></div><div className="fact"><span>{t.transaction}</span><strong>{order.transaction_id || check.receipt_or_transaction_id || '—'}</strong></div>{check.suspicious_signals?.length > 0 && <div className="warning-note"><AlertTriangle size={17}/><span>{t.anomalies}: {check.suspicious_signals.join(' · ')}</span></div>}<div className="admin-actions"><button className="secondary danger" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, false)}><XCircle size={17}/>{t.reject}</button><button className="primary" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, true)}><CheckCircle2 size={17}/>{t.approve}</button></div></section>; })}</main></div>;

  if (screen === 'help') return <div className="app-shell"><Header title={t.help}/><main className="page"><ConnectionBanner/><section className="analysis-card"><div className="card-head"><div><span className="section-kicker">KORGAN Legal AI</span><h2>{t.help}</h2></div><CircleHelp size={22}/></div><p>{t.helpText}</p></section><button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button></main><BottomNav/></div>;

  if (screen === 'profile') return <div className="app-shell"><Header title={t.profile}/><main className="page"><ConnectionBanner/><section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>{telegramUser?.firstName || 'KORGAN'}</h2><p>{telegramUser?.username ? `@${telegramUser.username}` : 'Telegram Mini App'}</p></div><span className={`profile-state ${backendOk ? 'ok' : 'down'}`}>{backendOk ? <BadgeCheck size={16}/> : <WifiOff size={16}/>}</span></section><section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>{t.language}</strong><small>Русский / Қазақша</small></div><div className="language-switch compact"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div></div></section>{pricing && <section className="analysis-card pricing-card"><div className="card-head"><div><span className="section-kicker">KORGAN</span><h2>{t.pricing}</h2></div><CreditCard size={22}/></div><div className="fact"><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div>{pricing.consultation_limit_enabled && <div className="fact"><span>{t.consultPrice}</span><strong>{money(pricing.consultation_price_kzt)}</strong></div>}{pricing.document_payments_enabled && <div className="fact"><span>{t.docPrice}</span><strong>{money(pricing.document_price_kzt)}</strong></div>}</section>}{pricing?.is_admin && <button className="primary wide admin-entry" onClick={openAdmin}><ClipboardCheck size={18}/>{t.admin}</button>}<section className="analysis-card system-card"><div className="card-head"><div><span className="section-kicker">SYSTEM</span><h2>{backendOk ? t.systemReady : t.systemProblem}</h2></div>{backendOk ? <BadgeCheck size={22}/> : <WifiOff size={22}/>}</div><div className="fact"><span>{t.runtime}</span><strong>{runtimeInfo?.parity?.service_outer || '—'}</strong></div><div className="fact"><span>{t.quality}</span><strong>{runtimeInfo?.word_quality_target || '—'}</strong></div><div className="fact"><span>{t.secure}</span><strong>AES-256-GCM</strong></div>{pricing?.document_payments_enabled && <div className="fact"><span>{t.manualCheck}</span><strong>{runtimeInfo?.parity?.receipt_verification_mode || 'kaspi_ofd_fiscal_qr_url'}</strong></div>}<button className="secondary wide compact-action" onClick={boot}><RefreshCw size={17}/>{t.refresh}</button></section><section className="privacy-card static"><LockKeyhole size={20}/><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div></section><button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button><button className="secondary wide danger" disabled={busy} onClick={deleteAllData}><Trash2 size={18}/>{t.deleteAll}</button></main><BottomNav/></div>;

  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div><div className={`top-status ${connection}`}><span/>{connection === 'ok' ? t.connected : connection === 'down' ? t.down : t.connecting}</div></header><main className="home-page"><ConnectionBanner/><section className="hero"><div className="hero-copy"><div className="online"><span className={backendOk ? 'online-dot' : 'offline-dot'}/>{backendOk ? t.systemReady : connection === 'checking' ? t.connecting : t.systemProblem}</div><h1>{t.heroTitle}</h1><p>{t.heroText}</p><button disabled={!backendOk} onClick={() => go('chat')}>{t.startConsult}<ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>{pricing && <section className="quick-stats"><div><MessageCircle size={17}/><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div><div><FileText size={17}/><span>{t.docPrice}</span><strong>{pricing.document_payments_enabled ? money(pricing.document_price_kzt) : '—'}</strong></div></section>}<section className="action-grid"><button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>{t.consultation}</h2><p>{t.consultationSub}</p></button><button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><h2>{t.prepare}</h2><p>{t.prepareSub}</p></button><button className="action-card" onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><div className="action-icon case"><FolderOpen/></div><h2>{t.myCases}</h2><p>{t.casesSub}</p></button><button className="action-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><h2>{t.privacy}</h2><p>{t.privacySub}</p></button></section><section className="privacy-card" onClick={() => go('profile')}><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div><ChevronRight size={18}/></section></main><BottomNav/></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
