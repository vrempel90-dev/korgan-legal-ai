import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertTriangle, ArrowLeft, BadgeCheck, Banknote, CheckCircle2, ChevronRight,
  CreditCard, Download, ExternalLink, FileSignature, FileText, FolderOpen,
  Headphones, Home, Languages, LoaderCircle, LockKeyhole, MessageCircle,
  Paperclip, RefreshCw, Reply, Scale, ScrollText, Search, Send, ShieldAlert,
  ShieldCheck, Sparkles, Trash2, UserRound,
} from 'lucide-react';
import './styles.css';
import { korganApi } from './korganApiV2';
import {
  acceptConsent as persistConsent,
  clearAllLocalData,
  loadState,
  setLanguage as persistLanguage,
} from './store';

const TERMS_VERSION = '2026-08-16-v1';
const LAWYER_URL = 'https://wa.me/77005000553';
const SUPPORT_URL = 'https://wa.me/77712841932';

const DOCS = [
  { id: 'claim', icon: Scale, ru: ['Исковое заявление', 'Иск в суд с проверкой права и расчётов'], kk: ['Талап қою арызы', 'Құқық пен есептер тексерілетін сот құжаты'] },
  { id: 'contract', icon: FileSignature, ru: ['Договор', 'Профессиональный договор с quality gate'], kk: ['Шарт', 'Сапа бақылауы бар кәсіби шарт'] },
  { id: 'response', icon: Reply, ru: ['Отзыв на иск', 'Возражения и позиция ответчика'], kk: ['Талапқа пікір', 'Жауапкердің ұстанымы мен қарсылықтары'] },
  { id: 'pretrial', icon: ScrollText, ru: ['Досудебная претензия', 'Требование до обращения в суд'], kk: ['Сотқа дейінгі талап', 'Сотқа жүгінуге дейінгі талап'] },
  { id: 'pretrial_response', icon: FileText, ru: ['Ответ на претензию', 'Позиция получателя претензии'], kk: ['Сотқа дейінгі талапқа жауап', 'Талап алушының ұстанымы'] },
];

const COPY = {
  ru: {
    home: 'Главная', cases: 'Дела', lawyer: 'AI-юрист', profile: 'Профиль',
    hero: 'Все функции AI-агента в Mini App',
    heroSub: 'Консультации, анализ материалов, пять типов документов, автоматическая проверка оплаты и production quality gates.',
    connected: 'AI-ядро подключено', down: 'AI-ядро временно недоступно',
    consult: 'Начать консультацию', docs: 'Подготовить документ', myCases: 'Мои дела',
    consentTitle: 'Условия использования',
    consentText: 'KORGAN работает с правом Республики Казахстан. Перед подачей документа проверьте персональные данные, доказательства, подсудность и суммы.',
    accept: 'Принимаю условия', selectDoc: 'Выберите документ', search: 'Поиск документа',
    newCase: 'Новое дело', describe: 'Опишите ситуацию',
    describeHint: 'Стороны, даты, суммы, нарушение, доказательства и желаемый результат.',
    create: 'Создать дело', upload: 'Загрузить документы / фото', files: 'Материалы',
    ask: 'Задать вопрос AI по делу', generate: 'Подготовить документ',
    generating: 'Проверяю право и формирую Word…', ready: 'Документ готов',
    payment: 'Оплата документа',
    paymentText: 'Оплатите через Kaspi и загрузите полный чек. KORGAN AI проверит получателя, сумму, время и номер операции и сразу запустит документ.',
    pay: 'Оплатить через Kaspi', receipt: 'Загрузить чек', receiptCheck: 'AI проверяет чек…',
    paidDocRetry: 'Оплата уже принята. Повторно платить не нужно — повторить генерацию',
    consultPay: 'Лимит бесплатных консультаций исчерпан. Оплатите одну консультацию и загрузите чек — AI проверит его и продолжит автоматически.',
    consultPaidRetry: 'Оплата уже подтверждена. Повторно платить не нужно — получить консультацию',
    send: 'Напишите юридический вопрос…', sources: 'Источники', free: 'Бесплатных консультаций осталось',
    delete: 'Удалить дело', deleteAll: 'Удалить все мои данные', lang: 'Язык',
    live: 'Связаться с живым юристом', support: 'Техподдержка', filingReady: 'Готов к подаче',
    preliminary: 'Предварительный документ', quality: 'Качество', status: 'Статус',
    download: 'Скачать DOCX', analysis: 'AI анализ материалов',
    analysisSub: 'Загрузите PDF, DOCX, TXT, JPG, PNG или WEBP и задавайте вопросы по материалам дела.',
    paySecurity: 'Та же защита оплаты, что в AI-агенте: fail-closed, anti-replay, конкретный получатель и привязка ко времени текущей заявки.',
  },
  kk: {
    home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль',
    hero: 'AI-агенттің барлық функциясы Mini App ішінде',
    heroSub: 'Кеңес, материал талдауы, бес құжат түрі, төлемді автоматты тексеру және production сапа бақылауы.',
    connected: 'AI-ядро қосылды', down: 'AI-ядро уақытша қолжетімсіз',
    consult: 'Кеңесті бастау', docs: 'Құжат дайындау', myCases: 'Менің істерім',
    consentTitle: 'Пайдалану шарттары',
    consentText: 'KORGAN Қазақстан Республикасының құқығымен жұмыс істейді. Құжатты берер алдында дербес деректерді, дәлелдерді, соттылықты және сомаларды тексеріңіз.',
    accept: 'Шарттарды қабылдаймын', selectDoc: 'Құжатты таңдаңыз', search: 'Құжатты іздеу',
    newCase: 'Жаңа іс', describe: 'Жағдайды сипаттаңыз',
    describeHint: 'Тараптар, күндер, сомалар, бұзушылық, дәлелдер және қажетті нәтиже.',
    create: 'Іс құру', upload: 'Құжаттар / фото жүктеу', files: 'Материалдар',
    ask: 'Іс бойынша AI-ға сұрақ қою', generate: 'Құжат дайындау',
    generating: 'Құқық тексеріліп, Word жасалуда…', ready: 'Құжат дайын',
    payment: 'Құжат төлемі',
    paymentText: 'Kaspi арқылы төлеңіз және толық чекті жүктеңіз. KORGAN AI алушыны, соманы, уақытты және операция нөмірін тексеріп, құжатты бірден бастайды.',
    pay: 'Kaspi арқылы төлеу', receipt: 'Чекті жүктеу', receiptCheck: 'AI чекті тексеруде…',
    paidDocRetry: 'Төлем қабылданды. Қайта төлеудің қажеті жоқ — генерацияны қайталау',
    consultPay: 'Тегін кеңес лимиті аяқталды. Бір кеңес үшін төлеңіз және чекті жүктеңіз — AI автоматты тексеріп жалғастырады.',
    consultPaidRetry: 'Төлем расталды. Қайта төлеудің қажеті жоқ — кеңесті алу',
    send: 'Заң сұрағын жазыңыз…', sources: 'Дереккөздер', free: 'Қалған тегін кеңес',
    delete: 'Істі жою', deleteAll: 'Барлық деректерімді жою', lang: 'Тіл',
    live: 'Тірі заңгермен байланысу', support: 'Техқолдау', filingReady: 'Беруге дайын',
    preliminary: 'Алдын ала құжат', quality: 'Сапа', status: 'Мәртебе',
    download: 'DOCX жүктеу', analysis: 'Материалдарды AI талдауы',
    analysisSub: 'PDF, DOCX, TXT, JPG, PNG немесе WEBP жүктеп, іс материалдары бойынша сұрақ қойыңыз.',
    paySecurity: 'AI-агенттегідей төлем қорғанысы: fail-closed, anti-replay, нақты алушы және ағымдағы өтінім уақытына байланыс.',
  },
};

const money = value => `${Number(value || 0).toLocaleString('ru-RU')} ₸`;
const docName = (id, lang) => (DOCS.find(item => item.id === id)?.[lang] || [id])[0];

function saveDoc(data, filename) {
  const bytes = Uint8Array.from(atob(data), char => char.charCodeAt(0));
  const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || 'KORGAN_document.docx';
  anchor.click();
  URL.revokeObjectURL(url);
}

function App() {
  const saved = loadState();
  const [language, setLanguage] = useState(saved.language === 'kk' ? 'kk' : 'ru');
  const [consent, setConsent] = useState(Boolean(saved.consentAccepted));
  const [screen, setScreen] = useState('home');
  const [online, setOnline] = useState(false);
  const [pricing, setPricing] = useState(null);
  const [cases, setCases] = useState([]);
  const [activeCase, setActiveCase] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState('claim');
  const [description, setDescription] = useState('');
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  const [chat, setChat] = useState([]);
  const [freeRemaining, setFreeRemaining] = useState(null);
  const [consultPayment, setConsultPayment] = useState(null);
  const [docPayment, setDocPayment] = useState(null);
  const [documentResult, setDocumentResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [receiptBusy, setReceiptBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const t = COPY[language];

  const refreshCases = async () => {
    const result = await korganApi.listCases();
    setCases(result.cases || []);
    return result.cases || [];
  };

  const boot = async () => {
    setNotice('');
    try {
      await korganApi.health();
      setOnline(true);
    } catch (error) {
      setOnline(false);
      setNotice(error?.message || t.down);
      return;
    }
    if (!consent) return;
    try {
      const [nextPricing, list, pendingConsult] = await Promise.all([
        korganApi.pricing(),
        korganApi.listCases(),
        korganApi.pendingConsultationPayment(),
      ]);
      setPricing(nextPricing);
      setCases(list.cases || []);
      if (pendingConsult?.payment_required && pendingConsult?.payment) {
        setConsultPayment(pendingConsult.payment);
        setScreen('chat');
      }
    } catch (error) {
      setNotice(error?.message || t.down);
    }
  };

  useEffect(() => {
    window.Telegram?.WebApp?.ready?.();
    window.Telegram?.WebApp?.expand?.();
    boot();
  }, [consent]);

  const changeLanguage = value => {
    const next = value === 'kk' ? 'kk' : 'ru';
    setLanguage(next);
    persistLanguage(next);
  };

  const acceptTerms = async () => {
    setBusy(true);
    try {
      await korganApi.acceptConsent(TERMS_VERSION);
      persistConsent(TERMS_VERSION);
      setConsent(true);
    } catch (error) {
      setNotice(error?.message || t.down);
    } finally {
      setBusy(false);
    }
  };

  const createCase = async () => {
    if (!description.trim()) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.createCase({ description: description.trim(), document_type: selectedDoc, language });
      setActiveCase(result.case);
      setDescription(''); setChat([]); setScreen('case');
      await refreshCases();
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const openCase = async item => {
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.getCase(item.id);
      setActiveCase(result.case);
      setChat((result.case.conversation || []).map(entry => ({ role: entry.role, text: entry.text, sources: entry.sources || [] })));
      setDocPayment(null); setDocumentResult(null); setScreen('case');
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const uploadMaterials = async event => {
    const files = Array.from(event.target.files || []); event.target.value = '';
    if (!activeCase || !files.length) return;
    setBusy(true); setNotice('');
    try {
      let latest = activeCase;
      for (const file of files) {
        const result = await korganApi.uploadMaterial(activeCase.id, file);
        latest = result.case || latest;
      }
      setActiveCase(latest);
      await refreshCases();
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const sendMessage = async () => {
    const question = message.trim();
    if (!question || busy || consultPayment) return;
    setMessage(''); setChat(prev => [...prev, { role: 'user', text: question, sources: [] }]); setBusy(true); setNotice('');
    try {
      const result = await korganApi.consultation(question, activeCase?.id || null, activeCase?.language || language);
      if (result.payment_required) {
        setConsultPayment(result.payment);
        setFreeRemaining(0);
      } else {
        setChat(prev => [...prev, { role: 'ai', text: result.answer, sources: result.sources || [] }]);
        if (typeof result.free_remaining === 'number') setFreeRemaining(result.free_remaining);
      }
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const uploadConsultReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || !consultPayment) return;
    setReceiptBusy(true); setNotice('');
    try {
      const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, file);
      setChat(prev => [...prev, { role: 'ai', text: result.answer, sources: result.sources || [] }]);
      setConsultPayment(null);
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };

  const retryPaidConsultation = async () => {
    if (!consultPayment?.order_id) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.retryPaidConsultation(consultPayment.order_id);
      setChat(prev => [...prev, { role: 'ai', text: result.answer, sources: result.sources || [] }]);
      setConsultPayment(null);
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const finishDocument = async result => {
    setDocumentResult(result); setDocPayment(null);
    setActiveCase(prev => prev ? {
      ...prev,
      status: result.status,
      title: result.title,
      has_document: true,
      filing_ready: result.filing_ready,
      release_status: result.release_status,
      quality_score: result.quality_score,
    } : prev);
    await refreshCases();
    setScreen('ready');
  };

  const generateDocument = async () => {
    if (!activeCase || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language);
      if (result.payment_required) {
        setDocPayment(result.payment); setScreen('payment');
      } else {
        await finishDocument(result);
      }
    } catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || !docPayment) return;
    setReceiptBusy(true); setNotice('');
    try { await finishDocument(await korganApi.uploadDocumentReceipt(docPayment.order_id, file)); }
    catch (error) { setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };

  const retryPaidDocument = async () => {
    if (!docPayment?.order_id) return;
    setBusy(true); setNotice('');
    try { await finishDocument(await korganApi.retryPaidDocument(docPayment.order_id)); }
    catch (error) { setNotice(error?.message || t.paidDocRetry); }
    finally { setBusy(false); }
  };

  const openExistingDocument = async () => {
    if (!activeCase) return;
    setBusy(true); setNotice('');
    try { setDocumentResult(await korganApi.getDocument(activeCase.id)); setScreen('ready'); }
    catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const deleteCase = async () => {
    if (!activeCase) return;
    setBusy(true);
    try { await korganApi.deleteCase(activeCase.id); setActiveCase(null); await refreshCases(); setScreen('cases'); }
    catch (error) { setNotice(error?.message || t.down); }
    finally { setBusy(false); }
  };

  const filteredDocs = useMemo(
    () => DOCS.filter(item => item[language].join(' ').toLowerCase().includes(search.toLowerCase())),
    [search, language],
  );

  const Header = ({ title, back = 'home' }) => (
    <header className="subbar">
      <button className="icon-btn" onClick={() => setScreen(back)}><ArrowLeft size={20} /></button>
      <strong>{title}</strong><span className="header-spacer" />
    </header>
  );
  const Nav = () => (
    <nav className="bottom-nav">
      <button onClick={() => setScreen('home')}><Home size={20} /><span>{t.home}</span></button>
      <button onClick={async () => { await refreshCases(); setScreen('cases'); }}><FolderOpen size={20} /><span>{t.cases}</span></button>
      <button onClick={() => setScreen('chat')}><MessageCircle size={20} /><span>{t.lawyer}</span></button>
      <button onClick={() => setScreen('profile')}><UserRound size={20} /><span>{t.profile}</span></button>
    </nav>
  );
  const Notice = () => notice ? <div className="warning-note"><AlertTriangle size={17} /><span>{notice}</span></div> : null;

  if (!consent) return (
    <div className="app-shell consent-shell"><main className="page consent-page">
      <div className="brand-mark large"><Scale size={28} /></div>
      <div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => changeLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => changeLanguage('kk')}>KK</button></div>
      <h1>{t.consentTitle}</h1>
      <section className="privacy-card static"><ShieldCheck size={22} /><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section>
      <section className="privacy-card static"><LockKeyhole size={22} /><div><strong>Privacy</strong><p>AES-256-GCM · Telegram initData · fail-closed</p></div></section>
      <Notice />
      <button className="primary wide" disabled={busy} onClick={acceptTerms}><ShieldCheck size={18} />{t.accept}</button>
    </main></div>
  );

  if (screen === 'documents') return (
    <div className="app-shell"><Header title={t.selectDoc} /><main className="page">
      <div className="search"><Search size={18} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={t.search} /></div>
      {pricing?.document_payments_enabled && <div className="price-note"><CreditCard size={16} /><span>{money(pricing.document_price_kzt)} · AI receipt verification</span></div>}
      <div className="list-card">{filteredDocs.map(item => { const Icon = item.icon; return (
        <button className="list-row" key={item.id} onClick={() => { setSelectedDoc(item.id); setScreen('new-case'); }}>
          <span className="row-icon"><Icon size={20} /></span><span><strong>{item[language][0]}</strong><small>{item[language][1]}</small></span><ChevronRight size={18} />
        </button>
      ); })}</div>
    </main><Nav /></div>
  );

  if (screen === 'new-case') return (
    <div className="app-shell"><Header title={t.newCase} back="documents" /><main className="page">
      <h1>{docName(selectedDoc, language)}</h1><p>{t.analysisSub}</p>
      <textarea className="case-input" value={description} onChange={event => setDescription(event.target.value)} placeholder={t.describeHint} />
      <Notice /><button className="primary wide" disabled={busy || !description.trim()} onClick={createCase}>{busy ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />}{t.create}</button>
    </main></div>
  );

  if (screen === 'cases') return (
    <div className="app-shell"><Header title={t.myCases} /><main className="page"><Notice />
      {cases.map(item => <button className="case-list-item" key={item.id} onClick={() => openCase(item)}><div className="case-badge"><Scale size={20} /></div><div><strong>{item.title || docName(item.document_type, language)}</strong><small>{item.id} · {item.materials_count || 0} {item.has_document ? '· DOCX' : ''}</small></div><ChevronRight size={18} /></button>)}
      <button className="primary wide" onClick={() => setScreen('documents')}>{t.docs}</button>
    </main><Nav /></div>
  );

  if (screen === 'case' && activeCase) return (
    <div className="app-shell"><Header title={activeCase.id} back="cases" /><main className="page">
      <section className="analysis-card"><span className="section-kicker">{docName(activeCase.document_type, language)}</span><h2>{activeCase.title || t.analysis}</h2><p>{activeCase.description}</p><div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count || 0}</strong></div>{typeof activeCase.quality_score === 'number' && <div className="fact"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}</section>
      <Notice />
      <label className="secondary wide"><Paperclip size={18} />{t.upload}<input className="hidden-input" multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterials} /></label>
      <button className="secondary wide" onClick={() => setScreen('chat')}><MessageCircle size={18} />{t.ask}</button>
      {activeCase.has_document && <button className="secondary wide" onClick={openExistingDocument}><Download size={18} />{t.download}</button>}
      <button className="primary wide" disabled={busy} onClick={generateDocument}>{busy ? <LoaderCircle className="spin" size={18} /> : <FileText size={18} />}{busy ? t.generating : `${t.generate}${pricing?.document_payments_enabled ? ` · ${money(pricing.document_price_kzt)}` : ''}`}</button>
      <button className="secondary danger wide" onClick={deleteCase}><Trash2 size={18} />{t.delete}</button>
    </main><Nav /></div>
  );

  if (screen === 'chat') return (
    <div className="app-shell chat-shell"><Header title={activeCase ? `${t.lawyer} · ${activeCase.id}` : t.lawyer} /><main className="chat-page">
      {freeRemaining !== null && <div className="quota-note"><BadgeCheck size={15} />{t.free}: <strong>{freeRemaining}</strong></div>}
      <div className="messages">{chat.map((entry, index) => <div key={index} className={`message-wrap ${entry.role === 'user' ? 'user-wrap' : 'ai-wrap'}`}><div className={`bubble ${entry.role === 'user' ? 'user' : 'ai'}`}>{entry.text}</div>{entry.sources?.length > 0 && <div className="source-list"><span>{t.sources}</span>{entry.sources.map((source, sourceIndex) => <a key={sourceIndex} href={source} target="_blank" rel="noreferrer">{source}</a>)}</div>}</div>)}</div>
      {consultPayment && <section className="payment-card"><h3>{t.consultPay}</h3><div className="payment-amount">{money(consultPayment.amount_kzt)}</div>
        {consultPayment.status === 'paid' ? (
          <button className="primary wide" disabled={busy} onClick={retryPaidConsultation}><RefreshCw size={18} />{t.consultPaidRetry}</button>
        ) : <>
          <button className="primary wide" onClick={() => window.open(consultPayment.kaspi_url, '_blank')}><CreditCard size={18} />{t.pay}<ExternalLink size={15} /></button>
          <label className="secondary wide"><Paperclip size={18} />{receiptBusy ? t.receiptCheck : t.receipt}<input className="hidden-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={uploadConsultReceipt} /></label>
        </>}
      </section>}
      <Notice /><div className="composer"><input value={message} onChange={event => setMessage(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') sendMessage(); }} disabled={Boolean(consultPayment)} placeholder={t.send} /><button onClick={sendMessage} disabled={busy || Boolean(consultPayment)}><Send size={19} /></button></div>
    </main><Nav /></div>
  );

  if (screen === 'payment' && docPayment) return (
    <div className="app-shell"><Header title={t.payment} back="case" /><main className="page payment-page">
      <div className="payment-stage-icon"><Banknote size={38} /></div><h1>{t.payment}</h1><p>{t.paymentText}</p><div className="payment-amount centered">{money(docPayment.amount_kzt)}</div>
      <section className="analysis-card"><ShieldCheck size={22} /><p>{t.paySecurity}</p></section><Notice />
      {docPayment.status === 'approved' ? <button className="primary wide" disabled={busy} onClick={retryPaidDocument}><RefreshCw size={18} />{t.paidDocRetry}</button> : <>
        <button className="primary wide" onClick={() => window.open(docPayment.kaspi_url, '_blank')}><CreditCard size={18} />{t.pay}<ExternalLink size={15} /></button>
        <label className="secondary wide"><Paperclip size={18} />{receiptBusy ? t.receiptCheck : t.receipt}<input className="hidden-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={uploadDocReceipt} /></label>
      </>}
    </main></div>
  );

  if (screen === 'ready' && documentResult) return (
    <div className="app-shell"><Header title={t.ready} back="case" /><main className="page ready-page">
      <div className={`success-ring ${documentResult.filing_ready ? '' : 'preliminary-ring'}`}>{documentResult.filing_ready ? <CheckCircle2 size={48} /> : <ShieldAlert size={44} />}</div>
      <span className={`release-badge ${documentResult.filing_ready ? 'ready' : 'preliminary'}`}>{documentResult.filing_ready ? t.filingReady : t.preliminary}</span>
      <h1>{documentResult.title || t.ready}</h1><div className="release-grid"><div><span>{t.quality}</span><strong>{typeof documentResult.quality_score === 'number' ? `${documentResult.quality_score}/10` : '—'}</strong></div><div><span>{t.status}</span><strong>{documentResult.release_status}</strong></div></div>
      <button className="primary wide" onClick={() => saveDoc(documentResult.document_base64, documentResult.filename)}><Download size={18} />{t.download}</button>
      <button className="lawyer-btn wide" onClick={() => window.open(LAWYER_URL, '_blank')}><ShieldCheck size={18} />{t.live}</button>
    </main></div>
  );

  if (screen === 'profile') return (
    <div className="app-shell"><Header title={t.profile} /><main className="page">
      <section className="profile-card"><div className="avatar"><UserRound size={30} /></div><div><h2>KORGAN</h2><p>{online ? t.connected : t.down}</p></div><BadgeCheck size={18} /></section>
      <section className="settings-card"><div className="settings-row"><Languages size={20} /><div><strong>{t.lang}</strong></div><div className="language-switch compact"><button className={language === 'ru' ? 'active' : ''} onClick={() => changeLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => changeLanguage('kk')}>KK</button></div></div></section>
      <button className="secondary wide" onClick={() => window.open(LAWYER_URL, '_blank')}><ShieldCheck size={18} />{t.live}</button>
      <button className="secondary wide" onClick={() => window.open(SUPPORT_URL, '_blank')}><Headphones size={18} />{t.support}</button>
      <button className="secondary danger wide" onClick={async () => { setBusy(true); try { await korganApi.deleteMyData(); clearAllLocalData(); setConsent(false); setCases([]); setConsultPayment(null); } finally { setBusy(false); } }}><Trash2 size={18} />{t.deleteAll}</button>
    </main><Nav /></div>
  );

  return (
    <div className="app-shell"><main className="page home-page"><div className="hero"><div className="brand-mark"><Scale size={26} /></div><span className="section-kicker">KORGANZAN.Ai</span><h1>{t.hero}</h1><p>{t.heroSub}</p><div className={`connection-note ${online ? '' : 'offline'}`}><span className={online ? 'dot on' : 'dot'} />{online ? t.connected : t.down}</div></div><Notice />
      <div className="home-actions"><button className="primary wide" onClick={() => setScreen('chat')}><MessageCircle size={19} />{t.consult}</button><button className="secondary wide" onClick={() => setScreen('documents')}><FileText size={19} />{t.docs}</button><button className="secondary wide" onClick={async () => { await refreshCases(); setScreen('cases'); }}><FolderOpen size={19} />{t.myCases}</button></div>
      <section className="analysis-card"><Sparkles size={22} /><h2>{t.analysis}</h2><p>{t.analysisSub}</p></section>
    </main><Nav /></div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
