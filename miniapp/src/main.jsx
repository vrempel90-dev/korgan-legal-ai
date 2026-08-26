import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home,
  UserRound, ArrowRight, ArrowLeft, Search, ChevronRight, CheckCircle2,
  ScrollText, Reply, Send, Download, LockKeyhole, Sparkles, Trash2,
  Languages, AlertTriangle, Paperclip, FileSignature, Headphones, CircleHelp,
  RefreshCw, ExternalLink, CreditCard, BadgeCheck, Clock3, WifiOff, Link2,
  LoaderCircle, ShieldAlert
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

const TEXT = {
  ru: {
    consentTitle: 'Условия использования KORGAN Legal AI',
    consentText: 'KORGAN — система искусственного интеллекта. Ответы и документы формируются автоматически по данным пользователя и проверенным источникам. Перед подачей документа проверьте персональные данные, суммы, доказательства, подсудность и госпошлину.',
    privacyText: 'Переданные данные используются для консультации, анализа материалов и формирования документов. Данные Mini App можно удалить в профиле.',
    accept: 'Принимаю условия', decline: 'Не принимаю', home: 'Главная', cases: 'Дела', lawyer: 'AI-юрист', profile: 'Профиль',
    yourLawyer: 'Профессиональный AI-юрист', hero: 'Консультации, анализ материалов и юридические документы в едином рабочем пространстве.', startConsult: 'Начать консультацию',
    consultation: 'Консультация', consultationSub: 'Правовой анализ с проверкой источников', prepare: 'Подготовить документ', prepareSub: 'Пять production-документов KORGAN в Word',
    myCases: 'Мои дела', casesSub: 'Материалы, история консультаций и документы', privacy: 'Конфиденциальность', privacySub: 'Согласие, язык и управление данными',
    selectDoc: 'Выбор документа', searchDoc: 'Поиск документа', documents: 'Документы', newCase: 'Новое дело', tell: 'Расскажите, что произошло',
    tellSub: 'Опишите ситуацию своими словами или сразу загрузите документы. KORGAN разберёт PDF, DOCX, TXT и фотографии и использует их как материалы дела.',
    placeholder: 'Стороны, договор/отношение, даты, суммы, нарушение, доказательства, позиция и чего вы хотите добиться...', create: 'Создать дело', creating: 'Создаю дело…',
    materials: 'Материалы дела', files: 'Файлов в деле', uploaded: 'Загружено', addFile: 'Загрузить документы / фото', processing: 'Обрабатываю материалы…',
    consultCase: 'Консультация по этому делу', generate: 'Подготовить документ по материалам', generating: 'Проверяю право и формирую…', deleteCase: 'Удалить дело',
    docReady: 'Документ готов', caseCreated: 'Дело создано', materialsLoaded: 'Материалы загружены', download: 'Скачать DOCX', downloadExisting: 'Скачать готовый DOCX',
    liveReview: 'Проверка юристом', noCases: 'Дел пока нет', noCasesSub: 'Создайте первое дело и опишите ситуацию своими словами.', createNew: 'Создать новое дело',
    language: 'Язык', deleteAll: 'Удалить все мои данные', dataControl: 'Данные под контролем', dataControlSub: 'Mini App работает через отдельный API и не изменяет production Telegram‑агента.',
    connected: 'KORGAN подключён', connecting: 'Проверяю соединение…', backendDown: 'Сервис временно недоступен', checking: 'Проверяю право и источники…', message: 'Напишите юридический вопрос…',
    status: 'Статус', check: 'Проверка', help: 'Помощь', support: 'Техподдержка', restored: 'История дела восстановлена', documentStored: 'Готовый документ сохранён в деле',
    helpText: 'Выберите тип документа, создайте дело, затем загрузите PDF/DOCX/TXT/фото. KORGAN извлечёт содержание, учтёт материалы вместе с вашими фактами, проверит правовые источники и подготовит Word через то же юридическое ядро, которое используется AI‑агентом.',
    retry: 'Повторить', source: 'Источник', sources: 'Источники', pricing: 'Тарифы и лимиты', freePerDay: 'Бесплатных консультаций в день', consultPrice: 'Консультация после лимита', docPrice: 'Подготовка документа',
    paymentNeeded: 'Лимит бесплатных консультаций исчерпан', paymentText: 'Оплатите консультацию через Kaspi, затем загрузите полный чек. После проверки KORGAN продолжит ответ по этому же вопросу.',
    payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек', checkingReceipt: 'Проверяю чек…', retryPaid: 'Повторить ответ без новой оплаты', paidSaved: 'Чек принят. Повторная оплата не требуется.',
    freeRemaining: 'Бесплатных консультаций осталось', filingReady: 'Готов к подаче', preliminary: 'Предварительный документ', verified: 'Проверки пройдены', needsCheck: 'Требуется проверка', quality: 'Качество', runtime: 'Юридическое ядро', secure: 'Защищённое хранение',
    openCase: 'Открыть дело', systemReady: 'Система готова', systemProblem: 'Есть проблема соединения', refresh: 'Обновить',
  },
  kk: {
    consentTitle: 'KORGAN Legal AI пайдалану шарттары',
    consentText: 'KORGAN — жасанды интеллект жүйесі. Жауаптар мен құжаттар пайдаланушы деректері және тексерілген дереккөздер негізінде жасалады. Құжатты берер алдында дербес деректерді, сомаларды, дәлелдемелерді, соттылықты және мемлекеттік бажды тексеріңіз.',
    privacyText: 'Берілген деректер кеңес беру, материалдарды талдау және құжаттарды қалыптастыру үшін пайдаланылады. Mini App деректерін профильден жоюға болады.',
    accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын', home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль',
    yourLawyer: 'Кәсіби AI-заңгер', hero: 'Кеңес, материалдарды талдау және заңдық құжаттар бір жұмыс кеңістігінде.', startConsult: 'Кеңесті бастау',
    consultation: 'Кеңес', consultationSub: 'Дереккөздерді тексеретін құқықтық талдау', prepare: 'Құжат дайындау', prepareSub: 'KORGAN-ның бес production Word-құжаты',
    myCases: 'Менің істерім', casesSub: 'Материалдар, кеңес тарихы және құжаттар', privacy: 'Құпиялылық', privacySub: 'Келісім, тіл және деректерді басқару',
    selectDoc: 'Құжатты таңдау', searchDoc: 'Құжатты іздеу', documents: 'Құжаттар', newCase: 'Жаңа іс', tell: 'Не болғанын жазыңыз',
    tellSub: 'Жағдайды өз сөзіңізбен сипаттаңыз немесе құжаттарды бірден жүктеңіз. KORGAN PDF, DOCX, TXT және фотосуреттерді талдап, іс материалдары ретінде пайдаланады.',
    placeholder: 'Тараптар, шарт/қатынас, күндер, сомалар, бұзушылық, дәлелдер, ұстаным және қалаған нәтиже...', create: 'Іс құру', creating: 'Іс құрылуда…',
    materials: 'Іс материалдары', files: 'Істегі файлдар', uploaded: 'Жүктелді', addFile: 'Құжаттар / фото жүктеу', processing: 'Материалдар өңделуде…',
    consultCase: 'Осы іс бойынша кеңес', generate: 'Материалдар бойынша құжат дайындау', generating: 'Құқық тексеріліп, құжат жасалуда…', deleteCase: 'Істі жою',
    docReady: 'Құжат дайын', caseCreated: 'Іс құрылды', materialsLoaded: 'Материалдар жүктелді', download: 'DOCX жүктеу', downloadExisting: 'Дайын DOCX жүктеу',
    liveReview: 'Заңгердің тексеруі', noCases: 'Әзірге іс жоқ', noCasesSub: 'Бірінші істі құрып, жағдайды өз сөзіңізбен жазыңыз.', createNew: 'Жаңа іс құру',
    language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API арқылы жұмыс істейді және production Telegram‑агентін өзгертпейді.',
    connected: 'KORGAN қосылды', connecting: 'Қосылым тексерілуде…', backendDown: 'Қызмет уақытша қолжетімсіз', checking: 'Құқық пен дереккөздер тексерілуде…', message: 'Заңдық сұрағыңызды жазыңыз…',
    status: 'Мәртебе', check: 'Тексеру', help: 'Көмек', support: 'Техқолдау', restored: 'Іс тарихы қалпына келтірілді', documentStored: 'Дайын құжат істе сақталған',
    helpText: 'Құжат түрін таңдаңыз, іс құрыңыз, содан кейін PDF/DOCX/TXT/фото жүктеңіз. KORGAN мазмұнын шығарып, оны сіз берген фактілермен бірге ескереді, құқықтық дереккөздерді тексеріп, AI‑агент пайдаланатын сол заңдық ядро арқылы Word дайындайды.',
    retry: 'Қайталау', source: 'Дереккөз', sources: 'Дереккөздер', pricing: 'Тарифтер мен лимиттер', freePerDay: 'Күніне тегін кеңес', consultPrice: 'Лимиттен кейінгі кеңес', docPrice: 'Құжат дайындау',
    paymentNeeded: 'Тегін кеңес лимиті аяқталды', paymentText: 'Kaspi арқылы кеңес ақысын төлеп, толық чекті жүктеңіз. Тексеруден кейін KORGAN осы сұрақ бойынша жауапты жалғастырады.',
    payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу', checkingReceipt: 'Чек тексерілуде…', retryPaid: 'Жаңа төлемсіз жауапты қайталау', paidSaved: 'Чек қабылданды. Қайта төлеу қажет емес.',
    freeRemaining: 'Қалған тегін кеңес', filingReady: 'Беруге дайын', preliminary: 'Алдын ала құжат', verified: 'Тексерулер өтті', needsCheck: 'Тексеру қажет', quality: 'Сапа', runtime: 'Заңдық ядро', secure: 'Қорғалған сақтау',
    openCase: 'Істі ашу', systemReady: 'Жүйе дайын', systemProblem: 'Қосылым мәселесі бар', refresh: 'Жаңарту',
  }
};

const docText = (id, lang) => {
  const item = DOCUMENTS.find(x => x.id === id);
  return item ? item[lang] : ['KORGAN Legal AI', ''];
};

const money = value => `${Number(value || 0).toLocaleString('ru-RU')} ₸`;
const safeUrl = value => /^https?:\/\//i.test(String(value || '').trim()) ? String(value).trim() : '';
const sourceLabel = value => {
  try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return String(value || ''); }
};

function downloadBase64(base64, filename) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'KORGAN_document.docx';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function App() {
  const initial = loadState();
  const [screen, setScreen] = useState('home');
  const [caseText, setCaseText] = useState(initial.draft?.description || '');
  const [selectedDocument, setSelectedDocument] = useState(initial.draft?.documentType || 'claim');
  const [pendingFiles, setPendingFiles] = useState([]);
  const [query, setQuery] = useState('');
  const [language, setLanguage] = useState(initial.language || 'ru');
  const [consent, setConsent] = useState(Boolean(initial.consentAccepted));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [chat, setChat] = useState([]);
  const [message, setMessage] = useState('');
  const [telegramUser, setTelegramUser] = useState(null);
  const [connection, setConnection] = useState('checking');
  const [cases, setCases] = useState([]);
  const [activeCase, setActiveCase] = useState(null);
  const [documentResult, setDocumentResult] = useState(null);
  const [pricing, setPricing] = useState(null);
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [freeRemaining, setFreeRemaining] = useState(null);
  const [paymentRequest, setPaymentRequest] = useState(null);
  const [receiptBusy, setReceiptBusy] = useState(false);
  const t = TEXT[language];
  const backendOk = connection === 'ok';

  const resetChat = () => {
    setPaymentRequest(null);
    setChat([{ from: 'ai', text: language === 'kk'
      ? 'Заңдық сұрағыңызды жазыңыз. Мен Қазақстан Республикасының құқығын және дереккөздерді тексеремін.'
      : 'Опишите юридический вопрос. Я проверю право Республики Казахстан и источники.' }]);
  };

  const boot = async () => {
    if (!consent || !isBackendConnected()) {
      setConnection(isBackendConnected() ? 'checking' : 'down');
      return;
    }
    setConnection('checking');
    try {
      const health = await korganApi.health();
      await korganApi.acceptConsent(TERMS_VERSION);
      const [caseResult, priceResult] = await Promise.all([
        korganApi.listCases(),
        korganApi.pricing().catch(() => null),
      ]);
      setRuntimeInfo(health);
      setPricing(priceResult);
      setCases(caseResult.cases || []);
      setConnection('ok');
    } catch (error) {
      setConnection('down');
      setNotice(error?.message || t.backendDown);
    }
  };

  useEffect(() => { initTelegram(); setTelegramUser(getTelegramUser()); }, []);
  useEffect(() => { if (!activeCase) resetChat(); }, [language]);
  useEffect(() => {
    if (!consent) return;
    boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consent]);

  const filteredDocuments = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return DOCUMENTS;
    return DOCUMENTS.filter(item => item[language].join(' ').toLowerCase().includes(q));
  }, [query, language]);

  const go = next => { haptic(); setNotice(''); setScreen(next); };
  const refreshCases = async () => {
    const result = await korganApi.listCases();
    const next = result.cases || [];
    setCases(next);
    return next;
  };
  const switchLanguage = next => { setLanguage(next); persistLanguage(next); };

  const acceptTerms = async () => {
    setBusy(true); setNotice('');
    try {
      if (!isBackendConnected()) throw new Error('KORGAN API не подключён');
      await korganApi.acceptConsent(TERMS_VERSION);
      acceptConsent(TERMS_VERSION);
      setConsent(true);
    } catch (error) {
      setNotice(error?.message || (language === 'kk' ? 'Келісімді сақтау мүмкін болмады.' : 'Не удалось сохранить согласие.'));
    } finally { setBusy(false); }
  };

  const declineTerms = async () => {
    try { if (isBackendConnected()) await korganApi.declineConsent(TERMS_VERSION); } catch {}
    clearAllLocalData();
    window.Telegram?.WebApp?.close?.();
  };

  const chooseDocument = id => {
    setSelectedDocument(id);
    setPendingFiles([]);
    saveDraft({ documentType: id });
    go('new-case');
  };
  const saveCaseText = value => { setCaseText(value); saveDraft({ description: value, documentType: selectedDocument }); };
  const chooseInitialFiles = event => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;
    setPendingFiles(files);
    setNotice(language === 'kk' ? `${files.length} файл таңдалды.` : `Выбрано файлов: ${files.length}. Они загрузятся после создания дела.`);
  };

  const createCase = async () => {
    if ((!caseText.trim() && !pendingFiles.length) || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.createCase({ description: caseText.trim(), document_type: selectedDocument, language });
      let createdCase = result.case;
      setActiveCase(createdCase);
      if (pendingFiles.length) {
        try {
          await korganApi.uploadMaterials(createdCase.id, pendingFiles, ({ current, total, file, result: uploadResult }) => {
            createdCase = uploadResult.case || createdCase;
            setActiveCase(createdCase);
            setNotice(language === 'kk' ? `${current}/${total}: «${file.name}» талданды.` : `${current}/${total}: «${file.name}» разобран и добавлен в дело.`);
          });
        } catch (uploadError) {
          const detail = await korganApi.getCase(createdCase.id).catch(() => null);
          if (detail?.case) createdCase = detail.case;
          setActiveCase(createdCase);
          await refreshCases();
          setPendingFiles([]); clearLocalCaseData(); setCaseText(''); setScreen('case');
          setNotice(uploadError.message || 'Дело создано, но один из файлов не удалось разобрать. Уже обработанные материалы сохранены.');
          return;
        }
      }
      setActiveCase(createdCase); setDocumentResult(null); resetChat(); await refreshCases();
      clearLocalCaseData(); setCaseText(''); setPendingFiles([]); setScreen('case');
    } catch (error) { setNotice(error?.message || 'Не удалось создать дело.'); }
    finally { setBusy(false); }
  };

  const openCase = async item => {
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getCase(item.id);
      const detail = result.case;
      setActiveCase(detail);
      const restored = (detail.conversation || []).map(entry => ({
        from: entry.role === 'user' ? 'user' : 'ai',
        text: entry.text || '',
        sources: entry.sources || [],
      }));
      setChat(restored.length ? restored : [{ from: 'ai', text: t.restored }]);
      setPaymentRequest(null);
      setDocumentResult(null);
      setScreen('case');
    } catch (error) { setNotice(error?.message || t.backendDown); }
    finally { setBusy(false); }
  };

  const uploadMaterial = async event => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length || !activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      let latestCase = activeCase;
      await korganApi.uploadMaterials(activeCase.id, files, ({ current, total, file, result }) => {
        latestCase = result.case || latestCase;
        setActiveCase(latestCase);
        setNotice(language === 'kk' ? `${current}/${total}: «${file.name}» талданды.` : `${current}/${total}: «${file.name}» разобран и добавлен.`);
      });
      setActiveCase(latestCase);
      await refreshCases();
      setNotice(language === 'kk' ? `${files.length} файл өңделді.` : `Обработано файлов: ${files.length}. KORGAN учтёт их в консультации и документе.`);
    } catch (error) { setNotice(error?.message || 'Не удалось разобрать один из материалов. Уже обработанные файлы сохранены.'); }
    finally { setBusy(false); }
  };

  const appendAnswer = result => {
    const answer = String(result?.answer || '').trim();
    if (answer) setChat(prev => [...prev, { from: 'ai', text: answer, sources: result.sources || [] }]);
    if (typeof result?.free_remaining === 'number') setFreeRemaining(result.free_remaining);
  };

  const sendMessage = async () => {
    const value = message.trim();
    if (!value || busy || !backendOk || paymentRequest) return;
    setMessage('');
    setChat(prev => [...prev, { from: 'user', text: value }]);
    setBusy(true);
    try {
      const result = await korganApi.consultation(value, activeCase?.id || null, activeCase?.language || language);
      if (result.payment_required && result.payment) {
        setFreeRemaining(0);
        setPaymentRequest({ ...result.payment, question: value, paidPending: false });
      } else {
        appendAnswer(result);
      }
    } catch (error) {
      setChat(prev => [...prev, { from: 'ai error', text: error?.message || t.backendDown }]);
    } finally { setBusy(false); }
  };

  const uploadReceipt = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !paymentRequest || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try {
      const result = await korganApi.uploadConsultationReceipt(paymentRequest.order_id, file);
      appendAnswer(result);
      setPaymentRequest(null);
    } catch (error) {
      if (error?.status === 503) {
        setPaymentRequest(prev => ({ ...prev, paidPending: true }));
        setNotice(t.paidSaved);
      } else {
        setNotice(error?.message || t.backendDown);
      }
    } finally { setReceiptBusy(false); }
  };

  const retryPaidConsultation = async () => {
    if (!paymentRequest?.order_id || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.retryPaidConsultation(paymentRequest.order_id);
      appendAnswer(result);
      setPaymentRequest(null);
    } catch (error) { setNotice(error?.message || t.backendDown); }
    finally { setBusy(false); }
  };

  const generateDocument = async () => {
    if (!activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language);
      setDocumentResult(result);
      setActiveCase(prev => ({ ...prev, status: result.status, title: result.title, verification_status: result.verification_status, has_document: true, filing_ready: result.filing_ready, release_status: result.release_status, quality_score: result.quality_score }));
      await refreshCases(); setScreen('ready');
    } catch (error) { setNotice(error?.message || 'Не удалось сформировать документ.'); }
    finally { setBusy(false); }
  };

  const downloadExisting = async () => {
    if (!activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getDocument(activeCase.id);
      setDocumentResult(result);
      downloadBase64(result.document_base64, result.filename);
    } catch (error) { setNotice(error?.message || 'Не удалось получить сохранённый документ.'); }
    finally { setBusy(false); }
  };

  const deleteCurrentCase = async () => {
    if (!activeCase || !window.confirm(language === 'kk' ? 'Бұл істі және барлық деректерін жою керек пе?' : 'Удалить это дело и все его данные?')) return;
    setBusy(true);
    try { await korganApi.deleteCase(activeCase.id); setActiveCase(null); setDocumentResult(null); resetChat(); await refreshCases(); setScreen('cases'); }
    catch (error) { setNotice(error?.message || 'Не удалось удалить дело.'); }
    finally { setBusy(false); }
  };

  const deleteAllData = async () => {
    if (!window.confirm(language === 'kk' ? 'Mini App-тағы барлық деректерді жою керек пе?' : 'Удалить все данные Mini App и все дела?')) return;
    setBusy(true);
    try {
      if (isBackendConnected()) await korganApi.deleteMyData();
      clearAllLocalData(); setCases([]); setActiveCase(null); setDocumentResult(null); setConsent(false); setCaseText(''); setPendingFiles([]); resetChat(); setScreen('home');
    } catch (error) { setNotice(error?.message || 'Удаление не завершено.'); }
    finally { setBusy(false); }
  };

  const Header = ({ title, back = 'home' }) => <header className="subbar">
    <button className="icon-btn" onClick={() => go(back)} aria-label="Back"><ArrowLeft size={20}/></button>
    <strong>{title}</strong><span className="header-spacer" />
  </header>;

  const BottomNav = () => <nav className="bottom-nav">
    <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>
    <button className={screen === 'cases' ? 'active' : ''} onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><FolderOpen size={20}/><span>{t.cases}</span></button>
    <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>
    <button className={screen === 'help' ? 'active' : ''} onClick={() => go('help')}><CircleHelp size={20}/><span>{t.help}</span></button>
    <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>
  </nav>;

  const ConnectionBanner = () => connection === 'down' ? <div className="connection-banner error-banner">
    <WifiOff size={18}/><div><strong>{t.systemProblem}</strong><small>{t.backendDown}</small></div>
    <button onClick={boot}><RefreshCw size={17}/>{t.retry}</button>
  </div> : null;

  const SourceList = ({ sources = [] }) => {
    if (!sources?.length) return null;
    return <div className="source-list"><span>{t.sources}</span>{sources.map((source, index) => {
      const url = safeUrl(source);
      return url ? <a key={`${source}-${index}`} href={url} target="_blank" rel="noreferrer"><Link2 size={13}/>{sourceLabel(url)}<ExternalLink size={12}/></a>
        : <span className="source-chip" key={`${source}-${index}`}><Link2 size={13}/>{source}</span>;
    })}</div>;
  };

  const PaymentCard = () => !paymentRequest ? null : <section className="payment-card">
    <div className="payment-icon"><CreditCard size={24}/></div>
    <div className="payment-head"><span className="section-kicker">KORGAN PAYMENT</span><h3>{t.paymentNeeded}</h3></div>
    <p>{paymentRequest.paidPending ? t.paidSaved : t.paymentText}</p>
    <div className="payment-amount">{money(paymentRequest.amount_kzt || pricing?.consultation_price_kzt)}</div>
    {!paymentRequest.paidPending && paymentRequest.kaspi_url && <button className="primary wide" onClick={() => window.open(paymentRequest.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button>}
    {!paymentRequest.paidPending && <label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadReceipt}/></label>}
    {paymentRequest.paidPending && <button className="primary wide" disabled={busy} onClick={retryPaidConsultation}>{busy ? <LoaderCircle className="spin" size={18}/> : <RefreshCw size={18}/>} {t.retryPaid}</button>}
  </section>;

  if (!consent) return <div className="app-shell consent-shell"><main className="page consent-page">
    <div className="brand-mark large"><Scale size={28}/></div>
    <div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div>
    <h1>{t.consentTitle}</h1>
    <section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section>
    <section className="privacy-card static"><LockKeyhole size={22}/><div><strong>{t.privacy}</strong><p>{t.privacyText}</p></div></section>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    <button className="primary wide" disabled={busy} onClick={acceptTerms}>{busy ? <LoaderCircle className="spin" size={18}/> : <ShieldCheck size={18}/>} {t.accept}</button>
    <button className="secondary wide" onClick={declineTerms}>{t.decline}</button>
    <small>v. {TERMS_VERSION}</small>
  </main></div>;

  if (screen === 'documents') return <div className="app-shell"><Header title={t.selectDoc}/><main className="page"><ConnectionBanner/>
    <div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t.searchDoc}/></div>
    {pricing?.document_payments_enabled && <div className="price-note"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong></span></div>}
    <div className="section-kicker list-kicker">{t.documents}</div><div className="list-card">{filteredDocuments.map(item => { const [title, subtitle] = item[language]; const Icon = item.icon; return <button className="list-row" key={item.id} onClick={() => chooseDocument(item.id)}><span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/></button>; })}</div>
  </main><BottomNav/></div>;

  if (screen === 'new-case') {
    const [documentTitle] = docText(selectedDocument, language);
    return <div className="app-shell"><Header title={t.newCase} back="documents"/><main className="page creation-page"><ConnectionBanner/>
      <div className="progress"><span className="done">1</span><i/><span>2</span><i/><span>3</span><i/><span>4</span></div>
      <div className="big-title"><span className="eyebrow">{documentTitle}</span><h1>{t.tell}</h1><p>{t.tellSub}</p></div>
      <textarea className="case-input" value={caseText} onChange={e => saveCaseText(e.target.value)} maxLength={8000} placeholder={t.placeholder}/>
      <div className="input-meta"><Sparkles size={17}/><span>{caseText.length}/8000</span></div>
      <label className="secondary wide"><Paperclip size={18}/>{busy ? t.processing : t.addFile}<input className="hidden-input" disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={chooseInitialFiles}/></label>
      {pendingFiles.length > 0 && <div className="success-note">{language === 'kk' ? `Таңдалды: ${pendingFiles.map(file => file.name).join(', ')}` : `Выбрано: ${pendingFiles.map(file => file.name).join(', ')}`}</div>}
      {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
      <button className="primary wide" disabled={(!caseText.trim() && !pendingFiles.length) || busy || !backendOk} onClick={createCase}>{busy ? <LoaderCircle className="spin" size={18}/> : <ArrowRight size={18}/>} {busy ? t.creating : t.create}</button>
    </main></div>;
  }

  if (screen === 'case') {
    if (!activeCase) return <div className="app-shell"><Header title={t.cases} back="cases"/><main className="page"><p>{t.noCases}</p></main><BottomNav/></div>;
    const [title] = docText(activeCase.document_type, language);
    const statusText = activeCase.status === 'document_ready' ? t.docReady : activeCase.status === 'materials_ready' ? t.materialsLoaded : t.caseCreated;
    return <div className="app-shell"><Header title={activeCase.id} back="cases"/><main className="page"><ConnectionBanner/>
      <section className="status-card"><div><span className="section-kicker">{t.status}</span><h2>{statusText}</h2></div><span className="pill success">{(activeCase.language || language).toUpperCase()}</span></section>
      <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">{t.materials}</span><h2>{activeCase.title || title}</h2></div><Sparkles size={22}/></div>
        {activeCase.description && <p className="case-description">{activeCase.description}</p>}
        <div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count || 0}</strong></div>
        {activeCase.material_names?.length > 0 && <div className="material-list">{activeCase.material_names.map(name => <span key={name}><Paperclip size={13}/>{name}</span>)}</div>}
        {activeCase.verification_status && <div className="fact"><span>{t.check}</span><strong>{activeCase.filing_ready ? t.verified : t.needsCheck}</strong></div>}
        {typeof activeCase.quality_score === 'number' && <div className="fact"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}
      </section>
      {notice && <div className="success-note">{notice}</div>}
      <label className="secondary wide"><Paperclip size={18}/>{busy ? t.processing : t.addFile}<input className="hidden-input" disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterial}/></label>
      <button className="secondary wide" onClick={() => go('chat')}><MessageCircle size={18}/>{t.consultCase}</button>
      {activeCase.has_document && <button className="secondary wide" disabled={busy} onClick={downloadExisting}><Download size={18}/>{t.downloadExisting}</button>}
      <button className="primary wide" disabled={busy || !backendOk} onClick={generateDocument}>{busy ? <LoaderCircle className="spin" size={18}/> : <FileText size={18}/>} {busy ? t.generating : t.generate}</button>
      <button className="secondary wide danger" disabled={busy} onClick={deleteCurrentCase}><Trash2 size={18}/>{t.deleteCase}</button>
    </main><BottomNav/></div>;
  }

  if (screen === 'chat') return <div className="app-shell chat-shell"><Header title={activeCase ? `${t.lawyer} · ${activeCase.id}` : t.lawyer}/><main className="chat-page">
    <div className={`connection-note ${backendOk ? '' : 'offline'}`}><span className={backendOk ? 'dot on' : 'dot'}/>{connection === 'checking' ? t.connecting : backendOk ? t.connected : t.backendDown}{!backendOk && <button className="mini-retry" onClick={boot}><RefreshCw size={14}/></button>}</div>
    {freeRemaining !== null && <div className="quota-note"><BadgeCheck size={15}/>{t.freeRemaining}: <strong>{freeRemaining}</strong></div>}
    <div className="messages">{chat.map((item, index) => <div key={index} className={`message-wrap ${item.from.startsWith('user') ? 'user-wrap' : 'ai-wrap'}`}>
      <div className={`bubble ${item.from}`}>{item.text}</div>
      {item.from.startsWith('ai') && <SourceList sources={item.sources}/>} 
    </div>)}{busy && !paymentRequest && <div className="message-wrap ai-wrap"><div className="bubble ai typing"><LoaderCircle className="spin" size={16}/>{t.checking}</div></div>}</div>
    <PaymentCard/>
    {notice && <div className="warning-note chat-warning"><AlertTriangle size={17}/>{notice}</div>}
    <div className="composer"><input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} disabled={Boolean(paymentRequest)} placeholder={paymentRequest ? t.paymentNeeded : t.message}/><button aria-label="Send" disabled={busy || !backendOk || Boolean(paymentRequest)} onClick={sendMessage}><Send size={19}/></button></div>
  </main><BottomNav/></div>;

  if (screen === 'ready') {
    const ready = Boolean(documentResult?.filing_ready);
    return <div className="app-shell"><Header title={t.docReady} back="case"/><main className="page ready-page">
      <div className={`success-ring ${ready ? '' : 'preliminary-ring'}`}>{ready ? <CheckCircle2 size={48}/> : <ShieldAlert size={44}/>}</div>
      <span className={`release-badge ${ready ? 'ready' : 'preliminary'}`}>{ready ? t.filingReady : t.preliminary}</span>
      <h1>{documentResult?.title || t.docReady}</h1>
      <p>{ready ? t.verified : t.needsCheck}</p>
      <div className="release-grid">
        <div><span>{t.quality}</span><strong>{typeof documentResult?.quality_score === 'number' ? `${documentResult.quality_score}/10` : '—'}</strong></div>
        <div><span>{t.check}</span><strong>{documentResult?.release_status || '—'}</strong></div>
      </div>
      {(documentResult?.verification_notes?.length > 0 || documentResult?.quality_issues?.length > 0) && <div className="warning-note left-note"><AlertTriangle size={17}/><span>{[...(documentResult.verification_notes || []), ...(documentResult.quality_issues || [])].filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</span></div>}
      <div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div>
      <button className="primary wide" disabled={!documentResult?.document_base64} onClick={() => downloadBase64(documentResult.document_base64, documentResult.filename)}><Download size={18}/>{t.download}</button>
      <button className="lawyer-btn wide" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button>
    </main></div>;
  }

  if (screen === 'cases') return <div className="app-shell"><Header title={t.myCases}/><main className="page"><ConnectionBanner/>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    {cases.length === 0 && <section className="analysis-card empty-card"><FolderOpen size={30}/><h2>{t.noCases}</h2><p>{t.noCasesSub}</p></section>}
    {cases.map(item => { const [title] = docText(item.document_type, language); return <button className="case-list-item" key={item.id} onClick={() => openCase(item)}><div className="case-badge"><Scale size={20}/></div><div><strong>{item.title || title}</strong><small>{item.id} · {item.materials_count || 0} файл(ов){item.has_document ? ' · DOCX' : ''}</small></div><ChevronRight size={18}/></button>; })}
    <button className="primary wide" onClick={() => go('documents')}>{t.createNew}</button>
  </main><BottomNav/></div>;

  if (screen === 'help') return <div className="app-shell"><Header title={t.help}/><main className="page"><ConnectionBanner/>
    <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">KORGAN Legal AI</span><h2>{t.help}</h2></div><CircleHelp size={22}/></div><p>{t.helpText}</p></section>
    <button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button>
    <button className="secondary wide" onClick={() => go('profile')}><LockKeyhole size={18}/>{t.privacy}</button>
  </main><BottomNav/></div>;

  if (screen === 'profile') return <div className="app-shell"><Header title={t.profile}/><main className="page"><ConnectionBanner/>
    <section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>{telegramUser?.firstName || 'KORGAN'}</h2><p>{telegramUser?.username ? `@${telegramUser.username}` : 'Telegram Mini App'}</p></div><span className={`profile-state ${backendOk ? 'ok' : 'down'}`}>{backendOk ? <BadgeCheck size={16}/> : <WifiOff size={16}/>}</span></section>
    <section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>{t.language}</strong><small>Русский / Қазақша</small></div><div className="language-switch compact"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div></div></section>
    {pricing && <section className="analysis-card pricing-card"><div className="card-head"><div><span className="section-kicker">KORGAN</span><h2>{t.pricing}</h2></div><CreditCard size={22}/></div>
      <div className="fact"><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div>
      {pricing.consultation_limit_enabled && <div className="fact"><span>{t.consultPrice}</span><strong>{money(pricing.consultation_price_kzt)}</strong></div>}
      {pricing.document_payments_enabled && <div className="fact"><span>{t.docPrice}</span><strong>{money(pricing.document_price_kzt)}</strong></div>}
    </section>}
    <section className="analysis-card system-card"><div className="card-head"><div><span className="section-kicker">SYSTEM</span><h2>{backendOk ? t.systemReady : t.systemProblem}</h2></div>{backendOk ? <BadgeCheck size={22}/> : <WifiOff size={22}/>}</div>
      <div className="fact"><span>{t.runtime}</span><strong>{runtimeInfo?.parity?.service_outer || '—'}</strong></div>
      <div className="fact"><span>{t.quality}</span><strong>{runtimeInfo?.word_quality_target || '—'}</strong></div>
      <div className="fact"><span>{t.secure}</span><strong>AES-256-GCM</strong></div>
      <button className="secondary wide compact-action" onClick={boot}><RefreshCw size={17}/>{t.refresh}</button>
    </section>
    <section className="privacy-card static"><LockKeyhole size={20}/><div><strong>{t.privacy}</strong><p>v. {TERMS_VERSION}</p></div></section>
    <button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button>
    <button className="secondary wide" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    <button className="secondary wide danger" disabled={busy} onClick={deleteAllData}><Trash2 size={18}/>{t.deleteAll}</button>
  </main><BottomNav/></div>;

  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div><div className={`top-status ${connection}`}><span/>{connection === 'ok' ? t.connected : connection === 'down' ? t.backendDown : t.connecting}</div></header><main className="home-page"><ConnectionBanner/>
    <section className="hero"><div className="hero-copy"><div className="online"><span className={backendOk ? 'online-dot' : 'offline-dot'}/>{backendOk ? t.systemReady : connection === 'checking' ? t.connecting : t.systemProblem}</div><h1>{t.yourLawyer}</h1><p>{t.hero}</p><button disabled={!backendOk} onClick={() => go('chat')}>{t.startConsult}<ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>
    {pricing && <section className="quick-stats"><div><MessageCircle size={17}/><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div><div><FileText size={17}/><span>{t.docPrice}</span><strong>{pricing.document_payments_enabled ? money(pricing.document_price_kzt) : '—'}</strong></div></section>}
    <section className="action-grid"><button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>{t.consultation}</h2><p>{t.consultationSub}</p></button><button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><h2>{t.prepare}</h2><p>{t.prepareSub}</p></button><button className="action-card" onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><div className="action-icon case"><FolderOpen/></div><h2>{t.myCases}</h2><p>{t.casesSub}</p></button><button className="action-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><h2>{t.privacy}</h2><p>{t.privacySub}</p></button></section>
    <section className="privacy-card" onClick={() => go('profile')}><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div><ChevronRight size={18}/></section>
  </main><BottomNav/></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
