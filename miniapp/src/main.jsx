import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home,
  UserRound, ArrowRight, ArrowLeft, Search, ChevronRight, CheckCircle2,
  ScrollText, Reply, Send, Download, LockKeyhole, Sparkles, Trash2,
  Languages, AlertTriangle, Paperclip, FileSignature, Headphones, CircleHelp
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
    yourLawyer: 'Ваш AI-юрист', hero: 'Юридическая помощь, документы и сопровождение дела в одном приложении.', startConsult: 'Начать консультацию',
    consultation: 'Консультация', consultationSub: 'KORGAN AI с проверкой правовых источников', prepare: 'Подготовить документ', prepareSub: 'Пять production-документов KORGAN в Word',
    myCases: 'Мои дела', casesSub: 'Дела, материалы, история и документы', privacy: 'Конфиденциальность', privacySub: 'Согласие, язык и удаление данных',
    selectDoc: 'Выбор документа', searchDoc: 'Поиск документа', documents: 'Документы', newCase: 'Новое дело', tell: 'Расскажите, что произошло',
    tellSub: 'Можно описать ситуацию своими словами или сразу загрузить документы. KORGAN разберёт PDF, DOCX, TXT и фотографии и использует их как материалы дела.',
    placeholder: 'Стороны, договор/отношение, даты, суммы, нарушение, доказательства, позиция и чего вы хотите добиться...', create: 'Создать дело', creating: 'Создаю дело…',
    materials: 'Материалы дела', files: 'Файлов в деле', uploaded: 'Загружено', addFile: 'Загрузить документы / фото', processing: 'Обрабатываю материалы…',
    consultCase: 'Консультация по этому делу', generate: 'Подготовить документ по материалам', generating: 'Проверяю право и формирую…', deleteCase: 'Удалить дело',
    docReady: 'Документ готов', caseCreated: 'Дело создано', materialsLoaded: 'Материалы загружены', download: 'Скачать DOCX', downloadExisting: 'Скачать готовый DOCX',
    liveReview: 'Проверка юристом', noCases: 'Дел пока нет', noCasesSub: 'Создайте первое дело и опишите ситуацию своими словами.', createNew: 'Создать новое дело',
    language: 'Язык', deleteAll: 'Удалить все мои данные', dataControl: 'Данные под контролем', dataControlSub: 'Mini App работает через отдельный API и не вмешивается в production-бота.',
    connected: 'AI подключён', connecting: 'Подключение…', backendDown: 'Backend недоступен', checking: 'Проверяю право и источники…', message: 'Напишите сообщение…',
    status: 'Статус', check: 'Проверка', help: 'Помощь', support: 'Техподдержка', restored: 'История дела восстановлена', documentStored: 'Готовый документ сохранён в деле',
    helpText: 'Выберите тип документа, создайте дело, затем загрузите один или несколько PDF/DOCX/TXT/фото. KORGAN извлечёт содержание, учтёт материалы вместе с вашими фактами, проверит правовые источники и подготовит Word тем же юридическим ядром, что используется в AI-агенте.',
  },
  kk: {
    consentTitle: 'KORGAN Legal AI пайдалану шарттары',
    consentText: 'KORGAN — жасанды интеллект жүйесі. Жауаптар мен құжаттар пайдаланушы деректері және тексерілген дереккөздер негізінде жасалады. Құжатты берер алдында дербес деректерді, сомаларды, дәлелдемелерді, соттылықты және мемлекеттік бажды тексеріңіз.',
    privacyText: 'Берілген деректер кеңес беру, материалдарды талдау және құжаттарды қалыптастыру үшін пайдаланылады. Mini App деректерін профильден жоюға болады.',
    accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын', home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль',
    yourLawyer: 'Сіздің AI-заңгеріңіз', hero: 'Заңдық көмек, құжаттар және істі сүйемелдеу бір қолданбада.', startConsult: 'Кеңесті бастау',
    consultation: 'Кеңес', consultationSub: 'Құқықтық дереккөздерді тексеретін KORGAN AI', prepare: 'Құжат дайындау', prepareSub: 'KORGAN-ның бес production Word-құжаты',
    myCases: 'Менің істерім', casesSub: 'Істер, материалдар, тарих және құжаттар', privacy: 'Құпиялылық', privacySub: 'Келісім, тіл және деректерді жою',
    selectDoc: 'Құжатты таңдау', searchDoc: 'Құжатты іздеу', documents: 'Құжаттар', newCase: 'Жаңа іс', tell: 'Не болғанын жазыңыз',
    tellSub: 'Жағдайды өз сөзіңізбен сипаттауға немесе құжаттарды бірден жүктеуге болады. KORGAN PDF, DOCX, TXT және фотосуреттерді талдап, іс материалдары ретінде пайдаланады.',
    placeholder: 'Тараптар, шарт/қатынас, күндер, сомалар, бұзушылық, дәлелдер, ұстаным және қалаған нәтиже...', create: 'Іс құру', creating: 'Іс құрылуда…',
    materials: 'Іс материалдары', files: 'Істегі файлдар', uploaded: 'Жүктелді', addFile: 'Құжаттар / фото жүктеу', processing: 'Материалдар өңделуде…',
    consultCase: 'Осы іс бойынша кеңес', generate: 'Материалдар бойынша құжат дайындау', generating: 'Құқық тексеріліп, құжат жасалуда…', deleteCase: 'Істі жою',
    docReady: 'Құжат дайын', caseCreated: 'Іс құрылды', materialsLoaded: 'Материалдар жүктелді', download: 'DOCX жүктеу', downloadExisting: 'Дайын DOCX жүктеу',
    liveReview: 'Заңгердің тексеруі', noCases: 'Әзірге іс жоқ', noCasesSub: 'Бірінші істі құрып, жағдайды өз сөзіңізбен жазыңыз.', createNew: 'Жаңа іс құру',
    language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API арқылы жұмыс істейді және production-ботқа араласпайды.',
    connected: 'AI қосылды', connecting: 'Қосылуда…', backendDown: 'Backend қолжетімсіз', checking: 'Құқық пен дереккөздер тексерілуде…', message: 'Хабарлама жазыңыз…',
    status: 'Мәртебе', check: 'Тексеру', help: 'Көмек', support: 'Техқолдау', restored: 'Іс тарихы қалпына келтірілді', documentStored: 'Дайын құжат істе сақталған',
    helpText: 'Құжат түрін таңдаңыз, іс құрыңыз, содан кейін бір немесе бірнеше PDF/DOCX/TXT/фото жүктеңіз. KORGAN мазмұнын шығарып, оны сіз берген фактілермен бірге ескереді, құқықтық дереккөздерді тексеріп, AI-агент пайдаланатын сол заңдық ядро арқылы Word дайындайды.',
  }
};

const docText = (id, lang) => {
  const item = DOCUMENTS.find(x => x.id === id);
  return item ? item[lang] : ['KORGAN Legal AI', ''];
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
  URL.revokeObjectURL(url);
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
  const [backendOk, setBackendOk] = useState(false);
  const [cases, setCases] = useState([]);
  const [activeCase, setActiveCase] = useState(null);
  const [documentResult, setDocumentResult] = useState(null);
  const t = TEXT[language];

  const resetChat = () => setChat([{ from: 'ai', text: language === 'kk' ? 'Заңдық сұрағыңызды жазыңыз. Мен Қазақстан Республикасының құқығын және дереккөздерді тексеремін.' : 'Опишите юридический вопрос. Я проверю право Республики Казахстан и источники.' }]);

  useEffect(() => { initTelegram(); setTelegramUser(getTelegramUser()); }, []);
  useEffect(() => { if (!activeCase) resetChat(); }, [language]);
  useEffect(() => {
    if (!consent || !isBackendConnected()) return;
    let cancelled = false;
    (async () => {
      try {
        const health = await korganApi.health();
        if (health.status !== 'ok') throw new Error('Backend health check failed');
        await korganApi.acceptConsent(TERMS_VERSION);
        const result = await korganApi.listCases();
        if (!cancelled) { setBackendOk(true); setCases(result.cases || []); }
      } catch { if (!cancelled) setBackendOk(false); }
    })();
    return () => { cancelled = true; };
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
      if (isBackendConnected()) await korganApi.acceptConsent(TERMS_VERSION);
      acceptConsent(TERMS_VERSION); setConsent(true); setBackendOk(isBackendConnected());
    } catch { setNotice(language === 'kk' ? 'Келісімді сақтау мүмкін болмады.' : 'Не удалось сохранить согласие.'); }
    finally { setBusy(false); }
  };

  const chooseDocument = id => { setSelectedDocument(id); setPendingFiles([]); saveDraft({ documentType: id }); go('new-case'); };
  const saveCaseText = value => { setCaseText(value); saveDraft({ description: value, documentType: selectedDocument }); };
  const chooseInitialFiles = event => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;
    setPendingFiles(files);
    setNotice(language === 'kk' ? `${files.length} файл таңдалды.` : `Выбрано файлов: ${files.length}. Они будут загружены сразу после создания дела.`);
  };

  const createCase = async () => {
    if ((!caseText.trim() && !pendingFiles.length) || busy) return;
    setBusy(true); setNotice('');
    try {
      const description = caseText.trim() || (language === 'kk'
        ? 'Іс жүктелген материалдар негізінде құрылды. Фактілерді тек пайдаланушы жүктеген құжаттардан алу керек.'
        : 'Дело создано на основании загруженных материалов. Факты следует брать только из документов, загруженных пользователем.');
      const result = await korganApi.createCase({ description, document_type: selectedDocument, language });
      let createdCase = result.case;
      setActiveCase(createdCase);

      if (pendingFiles.length) {
        try {
          await korganApi.uploadMaterials(createdCase.id, pendingFiles, ({ current, total, file, result: uploadResult }) => {
            createdCase = uploadResult.case || createdCase;
            setActiveCase(createdCase);
            setNotice(language === 'kk'
              ? `${current}/${total}: «${file.name}» талданды.`
              : `${current}/${total}: «${file.name}» разобран и добавлен в дело.`);
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
    } catch (e) { setNotice(e.message || 'Не удалось создать дело.'); }
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
        text: `${entry.text || ''}${entry.sources?.length ? `\n\n${language === 'kk' ? 'Дереккөздер' : 'Источники'}: ${entry.sources.join(' · ')}` : ''}`,
      }));
      setChat(restored.length ? restored : [{ from: 'ai', text: t.restored }]);
      setDocumentResult(null);
      setScreen('case');
    } catch (e) { setNotice(e.message || t.backendDown); }
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
        setNotice(language === 'kk'
          ? `${current}/${total}: «${file.name}» талданды және іске қосылды.`
          : `${current}/${total}: «${file.name}» разобран и добавлен в материалы дела.`);
      });
      setActiveCase(latestCase);
      await refreshCases();
      setNotice(language === 'kk'
        ? `${files.length} файл өңделді. KORGAN оларды осы іс бойынша кеңес пен құжат дайындауда ескереді.`
        : `Обработано файлов: ${files.length}. KORGAN учтёт их при консультации и подготовке документа по этому делу.`);
    } catch (e) { setNotice(e.message || 'Не удалось разобрать один из материалов. Уже успешно обработанные файлы сохранены в деле.'); }
    finally { setBusy(false); }
  };

  const sendMessage = async () => {
    const value = message.trim(); if (!value || busy || !backendOk) return;
    setMessage(''); setChat(prev => [...prev, { from: 'user', text: value }]); setBusy(true);
    try {
      const result = await korganApi.consultation(value, activeCase?.id || null, activeCase?.language || language);
      const sources = result.sources?.length ? `\n\n${language === 'kk' ? 'Дереккөздер' : 'Источники'}: ${result.sources.join(' · ')}` : '';
      setChat(prev => [...prev, { from: 'ai', text: `${result.answer || ''}${sources}` }]);
    } catch (e) { setChat(prev => [...prev, { from: 'ai', text: e.message || t.backendDown }]); }
    finally { setBusy(false); }
  };

  const generateDocument = async () => {
    if (!activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language);
      setDocumentResult(result);
      setActiveCase(prev => ({ ...prev, status: result.status, title: result.title, verification_status: result.verification_status, has_document: true }));
      await refreshCases(); setScreen('ready');
    } catch (e) { setNotice(e.message || 'Не удалось сформировать документ.'); }
    finally { setBusy(false); }
  };

  const downloadExisting = async () => {
    if (!activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getDocument(activeCase.id);
      setDocumentResult(result);
      downloadBase64(result.document_base64, result.filename);
    } catch (e) { setNotice(e.message || 'Не удалось получить сохранённый документ.'); }
    finally { setBusy(false); }
  };

  const deleteCurrentCase = async () => {
    if (!activeCase || !window.confirm(language === 'kk' ? 'Бұл істі және барлық деректерін жою керек пе?' : 'Удалить это дело и все его данные?')) return;
    setBusy(true);
    try { await korganApi.deleteCase(activeCase.id); setActiveCase(null); setDocumentResult(null); resetChat(); await refreshCases(); setScreen('cases'); }
    catch (e) { setNotice(e.message || 'Не удалось удалить дело.'); }
    finally { setBusy(false); }
  };

  const deleteAllData = async () => {
    if (!window.confirm(language === 'kk' ? 'Mini App-тағы барлық деректерді жою керек пе?' : 'Удалить все данные Mini App и все дела?')) return;
    setBusy(true);
    try {
      if (isBackendConnected()) await korganApi.deleteMyData();
      clearAllLocalData(); setCases([]); setActiveCase(null); setDocumentResult(null); setConsent(false); setCaseText(''); setPendingFiles([]); resetChat(); setScreen('home');
    } catch (e) { setNotice(e.message || 'Удаление не завершено.'); }
    finally { setBusy(false); }
  };

  const Header = ({ title, back = 'home' }) => <header className="subbar"><button className="icon-btn" onClick={() => go(back)}><ArrowLeft size={20}/></button><strong>{title}</strong><span className="header-spacer" /></header>;
  const BottomNav = () => <nav className="bottom-nav">
    <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>
    <button className={screen === 'cases' ? 'active' : ''} onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><FolderOpen size={20}/><span>{t.cases}</span></button>
    <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>
    <button className={screen === 'help' ? 'active' : ''} onClick={() => go('help')}><CircleHelp size={20}/><span>{t.help}</span></button>
    <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>
  </nav>;

  if (!consent) return <div className="app-shell consent-shell"><main className="page consent-page">
    <div className="brand-mark large"><Scale size={28}/></div>
    <div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div>
    <h1>{t.consentTitle}</h1>
    <section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section>
    <section className="privacy-card static"><LockKeyhole size={22}/><div><strong>{t.privacy}</strong><p>{t.privacyText}</p></div></section>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    <button className="primary wide" disabled={busy} onClick={acceptTerms}>{busy ? '...' : t.accept}</button>
    <button className="secondary wide" onClick={() => window.Telegram?.WebApp?.close?.()}>{t.decline}</button>
    <small>v. {TERMS_VERSION}</small>
  </main></div>;

  if (screen === 'documents') return <div className="app-shell"><Header title={t.selectDoc}/><main className="page">
    <div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t.searchDoc}/></div>
    <div className="section-kicker">{t.documents}</div><div className="list-card">{filteredDocuments.map(item => { const [title, subtitle] = item[language]; const Icon = item.icon; return <button className="list-row" key={item.id} onClick={() => chooseDocument(item.id)}><span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/></button>; })}</div>
  </main><BottomNav/></div>;

  if (screen === 'new-case') { const [documentTitle] = docText(selectedDocument, language); return <div className="app-shell"><Header title={t.newCase} back="documents"/><main className="page creation-page">
    <div className="progress"><span className="done">1</span><i/><span>2</span><i/><span>3</span><i/><span>4</span></div>
    <div className="big-title"><span className="eyebrow">{documentTitle}</span><h1>{t.tell}</h1><p>{t.tellSub}</p></div>
    <textarea className="case-input" value={caseText} onChange={e => saveCaseText(e.target.value)} maxLength={8000} placeholder={t.placeholder}/>
    <div className="input-meta"><Sparkles size={17}/><span>{caseText.length}/8000</span></div>
    <label className="secondary wide" style={{cursor:busy?'default':'pointer'}}><Paperclip size={18}/>{busy ? t.processing : t.addFile}<input style={{display:'none'}} disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={chooseInitialFiles}/></label>
    {pendingFiles.length > 0 && <div className="success-note">{language === 'kk' ? `Таңдалды: ${pendingFiles.map(file => file.name).join(', ')}` : `Выбрано: ${pendingFiles.map(file => file.name).join(', ')}`}</div>}
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    <button className="primary wide" disabled={(!caseText.trim() && !pendingFiles.length) || busy || !backendOk} onClick={createCase}>{busy ? t.creating : <>{t.create}<ArrowRight size={18}/></>}</button>
  </main></div>; }

  if (screen === 'case') {
    if (!activeCase) return <div className="app-shell"><Header title={t.cases} back="cases"/><main className="page"><p>{t.noCases}</p></main><BottomNav/></div>;
    const [title] = docText(activeCase.document_type, language);
    const statusText = activeCase.status === 'document_ready' ? t.docReady : activeCase.status === 'materials_ready' ? t.materialsLoaded : t.caseCreated;
    return <div className="app-shell"><Header title={activeCase.id} back="cases"/><main className="page">
      <section className="status-card"><div><span className="section-kicker">{t.status}</span><h2>{statusText}</h2></div><span className="pill success">{(activeCase.language || language).toUpperCase()}</span></section>
      <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">{t.materials}</span><h2>{activeCase.title || title}</h2></div><Sparkles size={22}/></div><p>{activeCase.description}</p><div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count || 0}</strong></div>{activeCase.material_names?.length > 0 && <div className="fact"><span>{t.uploaded}</span><strong>{activeCase.material_names.join(', ')}</strong></div>}{activeCase.verification_status && <div className="fact"><span>{t.check}</span><strong>{activeCase.verification_status}</strong></div>}</section>
      {notice && <div className="success-note">{notice}</div>}
      <label className="secondary wide" style={{cursor:busy?'default':'pointer'}}><Paperclip size={18}/>{busy ? t.processing : t.addFile}<input style={{display:'none'}} disabled={busy} multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterial}/></label>
      <button className="secondary wide" onClick={() => go('chat')}><MessageCircle size={18}/>{t.consultCase}</button>
      {activeCase.has_document && <button className="secondary wide" disabled={busy} onClick={downloadExisting}><Download size={18}/>{t.downloadExisting}</button>}
      <button className="primary wide" disabled={busy || !backendOk} onClick={generateDocument}>{busy ? t.generating : <><FileText size={18}/>{t.generate}</>}</button>
      <button className="secondary wide danger" disabled={busy} onClick={deleteCurrentCase}><Trash2 size={18}/>{t.deleteCase}</button>
    </main><BottomNav/></div>;
  }

  if (screen === 'chat') return <div className="app-shell chat-shell"><Header title={activeCase ? `${t.lawyer} · ${activeCase.id}` : t.lawyer}/><main className="chat-page">
    <div className="connection-note"><span className={backendOk ? 'dot on' : 'dot'}/>{backendOk ? t.connected : t.backendDown}</div>
    <div className="messages">{chat.map((m,i)=><div key={i} className={`bubble ${m.from}`}>{m.text}</div>)}{busy&&<div className="bubble ai">{t.checking}</div>}</div>
    <div className="composer"><input value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>e.key==='Enter'&&sendMessage()} placeholder={t.message}/><button disabled={busy||!backendOk} onClick={sendMessage}><Send size={19}/></button></div>
  </main><BottomNav/></div>;

  if (screen === 'ready') return <div className="app-shell"><Header title={t.docReady} back="case"/><main className="page ready-page">
    <div className="success-ring"><CheckCircle2 size={48}/></div><h1>{documentResult?.title || t.docReady}</h1><p>{documentResult?.verification_status || t.documentStored}</p>
    {documentResult?.verification_notes?.length > 0 && <div className="warning-note"><AlertTriangle size={17}/><span>{documentResult.verification_notes.join(' · ')}</span></div>}
    <div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div>
    <button className="primary wide" disabled={!documentResult?.document_base64} onClick={()=>downloadBase64(documentResult.document_base64,documentResult.filename)}><Download size={18}/>{t.download}</button>
    <button className="lawyer-btn" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button>
  </main></div>;

  if (screen === 'cases') return <div className="app-shell"><Header title={t.myCases}/><main className="page">
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    {cases.length===0&&<section className="analysis-card"><h2>{t.noCases}</h2><p>{t.noCasesSub}</p></section>}
    {cases.map(item=>{ const [title]=docText(item.document_type,language); return <section className="case-list-item" key={item.id} onClick={()=>openCase(item)}><div className="case-badge"><Scale size={20}/></div><div><strong>{item.title||title}</strong><small>{item.id} · {item.materials_count||0} файл(ов){item.has_document?' · DOCX':''}</small></div><ChevronRight size={18}/></section>; })}
    <button className="primary wide" onClick={()=>go('documents')}>{t.createNew}</button>
  </main><BottomNav/></div>;

  if (screen === 'help') return <div className="app-shell"><Header title={t.help}/><main className="page">
    <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">KORGAN Legal AI</span><h2>{t.help}</h2></div><CircleHelp size={22}/></div><p>{t.helpText}</p></section>
    <button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button>
    <button className="secondary wide" onClick={() => go('profile')}><LockKeyhole size={18}/>{t.privacy}</button>
  </main><BottomNav/></div>;

  if (screen === 'profile') return <div className="app-shell"><Header title={t.profile}/><main className="page">
    <section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>{telegramUser?.firstName||'KORGAN'}</h2><p>{telegramUser?.username?`@${telegramUser.username}`:'Telegram Mini App'}</p></div></section>
    <section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>{t.language}</strong><small>Русский / Қазақша</small></div><div className="language-switch compact"><button className={language==='ru'?'active':''} onClick={()=>switchLanguage('ru')}>RU</button><button className={language==='kk'?'active':''} onClick={()=>switchLanguage('kk')}>KK</button></div></div></section>
    <section className="privacy-card static"><LockKeyhole size={20}/><div><strong>{t.privacy}</strong><p>AES-256-GCM · retention 30 days · v. {TERMS_VERSION}</p></div></section>
    <button className="secondary wide" onClick={() => window.open(SUPPORT_WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><Headphones size={18}/>{t.support}</button>
    <button className="secondary wide" onClick={() => window.open(WHATSAPP_URL, '_blank', 'noopener,noreferrer')}><ShieldCheck size={18}/>{t.liveReview}</button>
    {notice&&<div className="success-note">{notice}</div>}
    <button className="secondary wide danger" disabled={busy} onClick={deleteAllData}><Trash2 size={18}/>{t.deleteAll}</button>
  </main><BottomNav/></div>;

  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div></header><main className="home-page">
    <section className="hero"><div className="hero-copy"><div className="online"><span/>{backendOk?t.connected:t.connecting}</div><h1>{t.yourLawyer}</h1><p>{t.hero}</p><button onClick={()=>go('chat')}>{t.startConsult}<ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>
    <section className="action-grid"><button className="action-card" onClick={()=>go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>{t.consultation}</h2><p>{t.consultationSub}</p></button><button className="action-card" onClick={()=>go('documents')}><div className="action-icon document"><FileText/></div><h2>{t.prepare}</h2><p>{t.prepareSub}</p></button><button className="action-card" onClick={async()=>{try{await refreshCases()}catch{}go('cases')}}><div className="action-icon case"><FolderOpen/></div><h2>{t.myCases}</h2><p>{t.casesSub}</p></button><button className="action-card" onClick={()=>go('profile')}><div className="action-icon review"><ShieldCheck/></div><h2>{t.privacy}</h2><p>{t.privacySub}</p></button></section>
    <section className="privacy-card" onClick={()=>go('profile')}><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>{t.dataControl}</strong><p>{t.dataControlSub}</p></div><ChevronRight size={18}/></section>
  </main><BottomNav/></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
