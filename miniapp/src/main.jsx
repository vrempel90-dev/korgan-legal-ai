import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home, Bell,
  UserRound, ArrowRight, ArrowLeft, Search, ChevronRight, CheckCircle2,
  BriefcaseBusiness, ShoppingCart, Building2, Landmark, HandCoins, Send,
  Download, LockKeyhole, Sparkles, Trash2, Languages, AlertTriangle
} from 'lucide-react';
import './styles.css';
import { isBackendConnected, korganApi } from './korganApi';
import {
  loadState, saveDraft, setLanguage as persistLanguage, acceptConsent,
  clearLocalCaseData, clearAllLocalData
} from './store';
import { getTelegramUser, initTelegram, haptic } from './telegram';

const TERMS_VERSION = '2026-08-16-v1';

const documents = [
  { id: 'claim', title: 'Исковое заявление', subtitle: 'Подготовка иска в суд', icon: Scale },
  { id: 'debt', title: 'Взыскание долга', subtitle: 'Договор, расписка, поставка', icon: HandCoins },
  { id: 'consumer', title: 'Защита прав потребителей', subtitle: 'Возврат товара, услуги, компенсация', icon: ShoppingCart },
  { id: 'housing', title: 'Жилищные споры', subtitle: 'Выселение, вселение, жильё', icon: Building2 },
  { id: 'labor', title: 'Трудовые споры', subtitle: 'Увольнение, зарплата, восстановление', icon: BriefcaseBusiness },
  { id: 'admin', title: 'Административная жалоба', subtitle: 'Действия госорганов и должностных лиц', icon: Landmark },
];

const copy = {
  ru: {
    consentTitle: 'Условия использования KORGAN Legal AI',
    consentText: 'KORGAN — система искусственного интеллекта. Ответы и документы формируются автоматически по данным пользователя и проверенным источникам. Перед подачей документа необходимо проверить персональные данные, суммы, доказательства, подсудность и госпошлину.',
    privacyText: 'Переданные данные используются для консультации, анализа материалов и формирования документов. Данные можно удалить в профиле.',
    accept: 'Принимаю условия', decline: 'Не принимаю',
  },
  kk: {
    consentTitle: 'KORGAN Legal AI пайдалану шарттары',
    consentText: 'KORGAN — жасанды интеллект жүйесі. Жауаптар мен құжаттар пайдаланушы берген деректер және тексерілген дереккөздер негізінде жасалады. Құжатты берер алдында дербес деректерді, сомаларды, дәлелдемелерді, соттылықты және мемлекеттік бажды тексеру қажет.',
    privacyText: 'Берілген деректер кеңес беру, материалдарды талдау және құжаттарды қалыптастыру үшін пайдаланылады. Деректерді профильде жоюға болады.',
    accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын',
  }
};

function downloadBase64(base64, filename, mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
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
  const [query, setQuery] = useState('');
  const [language, setLanguage] = useState(initial.language || 'ru');
  const [consent, setConsent] = useState(Boolean(initial.consentAccepted));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [chat, setChat] = useState([{ from: 'ai', text: 'Опишите юридический вопрос. Я проверю право Республики Казахстан и учту материалы выбранного дела.' }]);
  const [message, setMessage] = useState('');
  const [telegramUser, setTelegramUser] = useState(null);
  const [backendOk, setBackendOk] = useState(false);
  const [cases, setCases] = useState([]);
  const [activeCase, setActiveCase] = useState(null);
  const [documentResult, setDocumentResult] = useState(null);

  useEffect(() => {
    initTelegram();
    setTelegramUser(getTelegramUser());
  }, []);

  useEffect(() => {
    if (!consent || !isBackendConnected()) return;
    let cancelled = false;
    (async () => {
      try {
        await korganApi.health();
        // Staging API state is isolated and may restart independently. Reassert
        // the already accepted local terms before reading server-side cases.
        await korganApi.acceptConsent(TERMS_VERSION);
        const result = await korganApi.listCases();
        if (!cancelled) {
          setBackendOk(true);
          setCases(result.cases || []);
        }
      } catch {
        if (!cancelled) setBackendOk(false);
      }
    })();
    return () => { cancelled = true; };
  }, [consent]);

  const filteredDocuments = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? documents.filter(d => `${d.title} ${d.subtitle}`.toLowerCase().includes(q)) : documents;
  }, [query]);

  const go = (next) => { haptic(); setNotice(''); setScreen(next); };

  const refreshCases = async () => {
    if (!isBackendConnected()) return;
    const result = await korganApi.listCases();
    setCases(result.cases || []);
  };

  const chooseDocument = (id) => {
    setSelectedDocument(id);
    saveDraft({ documentType: id });
    go('new-case');
  };

  const saveCaseText = (value) => {
    setCaseText(value);
    saveDraft({ description: value, documentType: selectedDocument });
  };

  const acceptTerms = async () => {
    setBusy(true);
    try {
      if (isBackendConnected()) await korganApi.acceptConsent(TERMS_VERSION);
      acceptConsent(TERMS_VERSION);
      setConsent(true);
      setBackendOk(isBackendConnected());
    } catch {
      setNotice('Не удалось сохранить согласие на сервере. Попробуйте ещё раз.');
    } finally { setBusy(false); }
  };

  const switchLanguage = (next) => {
    setLanguage(next);
    persistLanguage(next);
  };

  const createCase = async () => {
    if (!caseText.trim() || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const result = await korganApi.createCase({
        description: caseText.trim(),
        document_type: selectedDocument || 'claim',
        language,
      });
      setActiveCase(result.case);
      setDocumentResult(null);
      await refreshCases();
      clearLocalCaseData();
      go('case');
    } catch (error) {
      setNotice(error.message || 'Не удалось создать дело.');
    } finally { setBusy(false); }
  };

  const openCase = (item) => {
    setActiveCase(item);
    setDocumentResult(null);
    go('case');
  };

  const sendMessage = async () => {
    const text = message.trim();
    if (!text || busy) return;
    setMessage('');
    setChat(prev => [...prev, { from: 'user', text }]);
    setBusy(true);
    try {
      const result = await korganApi.consultation(text, activeCase?.id || null, language);
      const sources = result.sources?.length ? `\n\nИсточники: ${result.sources.join(' · ')}` : '';
      setChat(prev => [...prev, { from: 'ai', text: `${result.answer || 'Ответ получен.'}${sources}` }]);
    } catch (error) {
      setChat(prev => [...prev, { from: 'ai', text: `Не удалось выполнить юридический запрос: ${error.message || 'повторите попытку'}.` }]);
    } finally { setBusy(false); }
  };

  const generateDocument = async () => {
    if (!activeCase || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const result = await korganApi.generateDocument(activeCase.id, activeCase.document_type || selectedDocument, language);
      setDocumentResult(result);
      setActiveCase(prev => prev ? { ...prev, status: result.status, title: result.title, verification_status: result.verification_status } : prev);
      await refreshCases();
      go('ready');
    } catch (error) {
      setNotice(error.message || 'Не удалось сформировать документ.');
    } finally { setBusy(false); }
  };

  const deleteCurrentCase = async () => {
    if (!activeCase || !window.confirm('Удалить это дело и все его данные?')) return;
    setBusy(true);
    try {
      await korganApi.deleteCase(activeCase.id);
      setActiveCase(null);
      setDocumentResult(null);
      await refreshCases();
      setNotice('Дело удалено.');
      setScreen('cases');
    } catch (error) {
      setNotice(error.message || 'Не удалось удалить дело.');
    } finally { setBusy(false); }
  };

  const deleteAllData = async () => {
    if (!window.confirm('Удалить все данные Mini App и все дела?')) return;
    setBusy(true);
    try {
      if (isBackendConnected()) await korganApi.deleteMyData();
      clearAllLocalData();
      setCases([]);
      setActiveCase(null);
      setDocumentResult(null);
      setConsent(false);
      setCaseText('');
      setScreen('home');
    } catch (error) {
      setNotice(error.message || 'Удаление не завершено.');
    } finally { setBusy(false); }
  };

  const Header = ({ title, back = 'home' }) => (
    <header className="subbar"><button className="icon-btn" onClick={() => go(back)}><ArrowLeft size={20}/></button><strong>{title}</strong><span className="header-spacer" /></header>
  );

  const BottomNav = () => (
    <nav className="bottom-nav">
      <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>Главная</span></button>
      <button className={screen === 'cases' ? 'active' : ''} onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><FolderOpen size={20}/><span>Дела</span></button>
      <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>AI-юрист</span></button>
      <button><Bell size={20}/><span>Уведомления</span></button>
      <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>Профиль</span></button>
    </nav>
  );

  if (!consent) {
    const t = copy[language];
    return <div className="app-shell consent-shell"><main className="page consent-page">
      <div className="brand-mark large"><Scale size={28}/></div>
      <div className="language-switch"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div>
      <h1>{t.consentTitle}</h1>
      <section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section>
      <section className="privacy-card static"><LockKeyhole size={22}/><div><strong>Конфиденциальность</strong><p>{t.privacyText}</p></div></section>
      {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
      <button className="primary wide" disabled={busy} onClick={acceptTerms}>{busy ? '...' : t.accept}</button>
      <button className="secondary wide" onClick={() => window.Telegram?.WebApp?.close?.()}>{t.decline}</button>
      <small>Версия условий: {TERMS_VERSION}</small>
    </main></div>;
  }

  if (screen === 'documents') return <div className="app-shell"><Header title="Выбор документа" /><main className="page">
    <div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск документа"/></div>
    <div className="section-kicker">Документы</div><div className="list-card">{filteredDocuments.map(({ id, title, subtitle, icon: Icon }) => <button className="list-row" key={id} onClick={() => chooseDocument(id)}><span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/></button>)}</div>
  </main><BottomNav /></div>;

  if (screen === 'new-case') return <div className="app-shell"><Header title="Новое дело" back="documents" /><main className="page creation-page">
    <div className="progress"><span className="done">1</span><i/><span>2</span><i/><span>3</span><i/><span>4</span></div>
    <div className="big-title"><span className="eyebrow">Шаг 1 из 4</span><h1>Расскажите, что произошло</h1><p>Опишите факты своими словами. KORGAN использует их как материалы дела и не должен придумывать отсутствующие сведения.</p></div>
    <textarea className="case-input" value={caseText} onChange={e => saveCaseText(e.target.value)} maxLength={8000} placeholder="Договор, стороны, даты, суммы, нарушение, претензии и чего вы хотите добиться..." />
    <div className="input-meta"><Sparkles size={17}/> Чем подробнее описание, тем точнее работа AI <span>{caseText.length}/8000</span></div>
    {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
    <button className="primary wide" disabled={!caseText.trim() || busy || !backendOk} onClick={createCase}>{busy ? 'Создаю дело…' : <>Создать дело <ArrowRight size={18}/></>}</button>
  </main></div>;

  if (screen === 'case') {
    const item = activeCase;
    if (!item) return <div className="app-shell"><Header title="Дело" back="cases" /><main className="page"><p>Выберите дело в разделе «Мои дела».</p></main><BottomNav /></div>;
    return <div className="app-shell"><Header title={`Дело ${item.id}`} back="cases" /><main className="page">
      <section className="status-card"><div><span className="section-kicker">Статус</span><h2>{item.status === 'document_ready' ? 'Документ готов' : 'Дело создано'}</h2></div><span className="pill success">{item.language?.toUpperCase() || language.toUpperCase()}</span></section>
      <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">Материалы дела</span><h2>{item.title || documents.find(d => d.id === item.document_type)?.title || 'Юридическое дело'}</h2></div><Sparkles size={22}/></div><p>{item.description}</p>{item.verification_status && <div className="fact"><span>Проверка</span><strong>{item.verification_status}</strong></div>}</section>
      {notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}
      <button className="secondary wide" onClick={() => go('chat')}><MessageCircle size={18}/> Консультация по этому делу</button>
      <button className="primary wide" disabled={busy} onClick={generateDocument}>{busy ? 'Проверяю право и формирую…' : <><FileText size={18}/> Сформировать документ</>}</button>
      <button className="secondary wide danger" disabled={busy} onClick={deleteCurrentCase}><Trash2 size={18}/> Удалить дело</button>
    </main><BottomNav /></div>;
  }

  if (screen === 'chat') return <div className="app-shell chat-shell"><Header title={activeCase ? `AI-юрист · ${activeCase.id}` : 'Чат с AI-юристом'} /><main className="chat-page">
    <div className="connection-note"><span className={backendOk ? 'dot on' : 'dot'} /> {backendOk ? 'KORGAN AI подключён' : 'Backend недоступен'}</div>
    <div className="messages">{chat.map((m, i) => <div key={i} className={`bubble ${m.from}`}>{m.text}</div>)}{busy && <div className="bubble ai">Проверяю право и источники…</div>}</div>
    <div className="composer"><input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendMessage()} placeholder="Напишите сообщение…"/><button disabled={busy || !backendOk} onClick={sendMessage}><Send size={19}/></button></div>
  </main><BottomNav /></div>;

  if (screen === 'ready') return <div className="app-shell"><Header title="Документ готов" back="case" /><main className="page ready-page">
    <div className="success-ring"><CheckCircle2 size={48}/></div><h1>{documentResult?.title || 'Документ сформирован'}</h1><p>{documentResult?.verification_status || 'Перед подачей проверьте реквизиты, факты, суммы и приложения.'}</p>
    {documentResult?.verification_notes?.length > 0 && <div className="warning-note"><AlertTriangle size={17}/><span>{documentResult.verification_notes.join(' · ')}</span></div>}
    <div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div>
    <button className="primary wide" disabled={!documentResult?.document_base64} onClick={() => downloadBase64(documentResult.document_base64, documentResult.filename)}><Download size={18}/> Скачать DOCX</button>
    <button className="lawyer-btn"><ShieldCheck size={18}/> Проверка живым юристом — скоро</button>
  </main></div>;

  if (screen === 'cases') return <div className="app-shell"><Header title="Мои дела" /><main className="page">
    {cases.length === 0 && <section className="analysis-card"><h2>Дел пока нет</h2><p>Создайте первое дело и опишите ситуацию своими словами.</p></section>}
    {cases.map(item => <section className="case-list-item" key={item.id} onClick={() => openCase(item)}><div className="case-badge"><Scale size={20}/></div><div><strong>{item.title || documents.find(d => d.id === item.document_type)?.title || 'Юридическое дело'}</strong><small>{item.id} · {item.status === 'document_ready' ? 'документ готов' : 'создано'}</small></div><ChevronRight size={18}/></section>)}
    <button className="primary wide" onClick={() => go('documents')}>Создать новое дело</button>
  </main><BottomNav /></div>;

  if (screen === 'profile') return <div className="app-shell"><Header title="Профиль" /><main className="page">
    <section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>{telegramUser?.firstName || 'Пользователь KORGAN'}</h2><p>{telegramUser?.username ? `@${telegramUser.username}` : 'Telegram Mini App'}</p></div></section>
    <section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>Язык</strong><small>Русский / Қазақша</small></div><div className="language-switch compact"><button className={language === 'ru' ? 'active' : ''} onClick={() => switchLanguage('ru')}>RU</button><button className={language === 'kk' ? 'active' : ''} onClick={() => switchLanguage('kk')}>KK</button></div></div></section>
    <section className="privacy-card static"><LockKeyhole size={20}/><div><strong>Конфиденциальность</strong><p>Версия условий: {TERMS_VERSION}. Дела Mini App изолированы от production-сессии Telegram-бота.</p></div></section>
    {notice && <div className="success-note">{notice}</div>}
    <button className="secondary wide danger" disabled={busy} onClick={deleteAllData}><Trash2 size={18}/> Удалить все мои данные</button>
  </main><BottomNav /></div>;

  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div></header><main className="home-page">
    <section className="hero"><div className="hero-copy"><div className="online"><span/> {backendOk ? 'AI подключён' : 'Подключение…'}</div><h1>Ваш AI-юрист</h1><p>Юридическая помощь, документы и сопровождение дела в одном приложении.</p><button onClick={() => go('chat')}>Начать консультацию <ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>
    <section className="action-grid"><button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>Консультация</h2><p>Реальный KORGAN AI и проверка источников</p></button><button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><h2>Подготовить документ</h2><p>Создайте дело и сформируйте DOCX</p></button><button className="action-card" onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><div className="action-icon case"><FolderOpen/></div><h2>Мои дела</h2><p>Дела, статусы и документы</p></button><button className="action-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><h2>Конфиденциальность</h2><p>Согласие, язык и удаление данных</p></button></section>
    <section className="privacy-card" onClick={() => go('profile')}><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>Данные под контролем</strong><p>Mini App работает через отдельный API и не вмешивается в production-бота.</p></div><ChevronRight size={18}/></section>
  </main><BottomNav /></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
