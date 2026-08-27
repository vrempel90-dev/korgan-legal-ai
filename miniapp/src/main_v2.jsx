import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home, UserRound,
  ArrowLeft, ChevronRight, CheckCircle2, ScrollText, Reply, Send, Download,
  Sparkles, Trash2, Languages, AlertTriangle, Paperclip, FileSignature,
  Headphones, RefreshCw, ExternalLink, CreditCard, BadgeCheck, LoaderCircle,
  ShieldAlert, Banknote, Search, LockKeyhole
} from 'lucide-react';
import './styles.css';
import { korganApi } from './korganApiV2';
import { acceptConsent as persistConsent, clearAllLocalData, loadState, setLanguage as persistLanguage } from './store';

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

const T = {
  ru: {
    home: 'Главная', cases: 'Дела', lawyer: 'AI-юрист', profile: 'Профиль',
    title: 'KORGAN Legal AI', hero: 'Все функции AI-агента в Mini App',
    heroSub: 'Консультации, анализ материалов, документы, автоматическая проверка оплаты и production quality gates.',
    consult: 'Начать консультацию', docs: 'Подготовить документ', myCases: 'Мои дела',
    connected: 'AI-ядро подключено', down: 'AI-ядро временно недоступно', retry: 'Повторить',
    consentTitle: 'Условия использования', consentText: 'KORGAN работает с правом Республики Казахстан. Перед подачей документа проверьте персональные данные, доказательства, подсудность и суммы.',
    accept: 'Принимаю условия', decline: 'Не принимаю',
    selectDoc: 'Выберите документ', search: 'Поиск документа', newCase: 'Новое дело',
    describe: 'Опишите ситуацию', describeHint: 'Стороны, даты, суммы, нарушение, доказательства и желаемый результат.',
    create: 'Создать дело', upload: 'Загрузить документы / фото', files: 'Материалы', ask: 'Задать вопрос AI по делу',
    generate: 'Подготовить документ', generating: 'Проверяю право и формирую Word…', ready: 'Документ готов',
    payment: 'Оплата документа', paymentText: 'Оплатите через Kaspi и загрузите полный чек. KORGAN AI проверит получателя, сумму, время и номер операции и сразу запустит документ.',
    pay: 'Оплатить через Kaspi', receipt: 'Загрузить чек', receiptCheck: 'AI проверяет чек…',
    paidRetry: 'Оплата уже принята. Повторно платить не нужно — повторите генерацию.',
    consultationLimit: 'Лимит бесплатных консультаций исчерпан. Оплатите одну консультацию и загрузите чек — AI продолжит автоматически.',
    send: 'Напишите юридический вопрос…', sources: 'Источники', free: 'Бесплатных консультаций осталось',
    delete: 'Удалить дело', deleteAll: 'Удалить все мои данные', lang: 'Язык', live: 'Связаться с живым юристом', support: 'Техподдержка',
    filingReady: 'Готов к подаче', preliminary: 'Предварительный документ', quality: 'Качество', status: 'Статус', download: 'Скачать DOCX',
    analysis: 'AI анализ материалов', analysisSub: 'Загрузите PDF, DOCX, TXT, JPG, PNG или WEBP и задавайте вопросы по этим материалам.',
    paySecurity: 'Та же проверка оплаты, что в AI-агенте: fail-closed, anti-replay, конкретный получатель и привязка ко времени текущей заявки.',
  },
  kk: {
    home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль',
    title: 'KORGAN Legal AI', hero: 'AI-агенттің барлық функциясы Mini App ішінде',
    heroSub: 'Кеңес, материал талдауы, құжаттар, төлемді автоматты тексеру және production сапа бақылауы.',
    consult: 'Кеңесті бастау', docs: 'Құжат дайындау', myCases: 'Менің істерім',
    connected: 'AI-ядро қосылды', down: 'AI-ядро уақытша қолжетімсіз', retry: 'Қайталау',
    consentTitle: 'Пайдалану шарттары', consentText: 'KORGAN Қазақстан Республикасының құқығымен жұмыс істейді. Құжатты берер алдында дербес деректерді, дәлелдерді, соттылықты және сомаларды тексеріңіз.',
    accept: 'Шарттарды қабылдаймын', decline: 'Қабылдамаймын',
    selectDoc: 'Құжатты таңдаңыз', search: 'Құжатты іздеу', newCase: 'Жаңа іс',
    describe: 'Жағдайды сипаттаңыз', describeHint: 'Тараптар, күндер, сомалар, бұзушылық, дәлелдер және қажетті нәтиже.',
    create: 'Іс құру', upload: 'Құжаттар / фото жүктеу', files: 'Материалдар', ask: 'Іс бойынша AI-ға сұрақ қою',
    generate: 'Құжат дайындау', generating: 'Құқық тексеріліп, Word жасалуда…', ready: 'Құжат дайын',
    payment: 'Құжат төлемі', paymentText: 'Kaspi арқылы төлеңіз және толық чекті жүктеңіз. KORGAN AI алушыны, соманы, уақытты және операция нөмірін тексеріп, құжатты бірден бастайды.',
    pay: 'Kaspi арқылы төлеу', receipt: 'Чекті жүктеу', receiptCheck: 'AI чекті тексеруде…',
    paidRetry: 'Төлем қабылданды. Қайта төлеудің қажеті жоқ — генерацияны қайталаңыз.',
    consultationLimit: 'Тегін кеңес лимиті аяқталды. Бір кеңес үшін төлеңіз және чекті жүктеңіз — AI автоматты жалғастырады.',
    send: 'Заң сұрағын жазыңыз…', sources: 'Дереккөздер', free: 'Қалған тегін кеңес',
    delete: 'Істі жою', deleteAll: 'Барлық деректерімді жою', lang: 'Тіл', live: 'Тірі заңгермен байланысу', support: 'Техқолдау',
    filingReady: 'Беруге дайын', preliminary: 'Алдын ала құжат', quality: 'Сапа', status: 'Мәртебе', download: 'DOCX жүктеу',
    analysis: 'Материалдарды AI талдауы', analysisSub: 'PDF, DOCX, TXT, JPG, PNG немесе WEBP жүктеп, осы материалдар бойынша сұрақ қойыңыз.',
    paySecurity: 'AI-агенттегідей төлем тексеруі: fail-closed, anti-replay, нақты алушы және ағымдағы өтінім уақытына байланыс.',
  },
};

const money = n => `${Number(n || 0).toLocaleString('ru-RU')} ₸`;
const docName = (id, lang) => (DOCS.find(x => x.id === id)?.[lang] || [id])[0];

function downloadBase64(data, filename) {
  const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a');
  a.href = url; a.download = filename || 'KORGAN_document.docx'; a.click(); URL.revokeObjectURL(url);
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
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState('');
  const [chat, setChat] = useState([]);
  const [freeRemaining, setFreeRemaining] = useState(null);
  const [consultPayment, setConsultPayment] = useState(null);
  const [docPayment, setDocPayment] = useState(null);
  const [documentResult, setDocumentResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [receiptBusy, setReceiptBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const t = T[language];

  const boot = async () => {
    setNotice('');
    try { await korganApi.health(); setOnline(true); }
    catch (e) { setOnline(false); setNotice(e?.message || t.down); return; }
    if (consent) {
      try {
        const [p, list] = await Promise.all([korganApi.pricing(), korganApi.listCases()]);
        setPricing(p); setCases(list.cases || []);
      } catch (e) { setNotice(e?.message || t.down); }
    }
  };
  useEffect(() => { window.Telegram?.WebApp?.ready?.(); window.Telegram?.WebApp?.expand?.(); boot(); }, [consent]);

  const changeLanguage = lang => { const next = lang === 'kk' ? 'kk' : 'ru'; setLanguage(next); persistLanguage(next); };
  const acceptTerms = async () => { setBusy(true); try { await korganApi.acceptConsent(TERMS_VERSION); persistConsent(TERMS_VERSION); setConsent(true); } catch (e) { setNotice(e?.message || t.down); } finally { setBusy(false); } };
  const refreshCases = async () => { const r = await korganApi.listCases(); setCases(r.cases || []); return r.cases || []; };

  const createCase = async () => {
    if (!description.trim()) return; setBusy(true); setNotice('');
    try { const r = await korganApi.createCase({ description: description.trim(), document_type: selectedDoc, language }); setActiveCase(r.case); setDescription(''); setChat([]); setScreen('case'); await refreshCases(); }
    catch (e) { setNotice(e?.message || t.down); } finally { setBusy(false); }
  };
  const openCase = async item => { setBusy(true); try { const r = await korganApi.getCase(item.id); setActiveCase(r.case); setChat((r.case.conversation || []).map(x => ({ role: x.role, text: x.text, sources: x.sources || [] }))); setDocPayment(null); setDocumentResult(null); setScreen('case'); } catch (e) { setNotice(e?.message || t.down); } finally { setBusy(false); } };
  const uploadMaterials = async e => { const files = Array.from(e.target.files || []); e.target.value=''; if (!activeCase || !files.length) return; setBusy(true); try { let latest=activeCase; for (const f of files) { const r=await korganApi.uploadMaterial(activeCase.id,f); latest=r.case || latest; } setActiveCase(latest); setNotice(`${t.files}: ${files.length}`); await refreshCases(); } catch(err){ setNotice(err?.message||t.down); } finally{setBusy(false);} };

  const sendMessage = async () => {
    const q=message.trim(); if(!q||busy||consultPayment)return; setMessage(''); setChat(x=>[...x,{role:'user',text:q,sources:[]}]); setBusy(true);
    try { const r=await korganApi.consultation(q,activeCase?.id||null,activeCase?.language||language); if(r.payment_required){setConsultPayment(r.payment);setFreeRemaining(0);} else {setChat(x=>[...x,{role:'ai',text:r.answer,sources:r.sources||[]}]); if(typeof r.free_remaining==='number')setFreeRemaining(r.free_remaining);} }
    catch(e){setNotice(e?.message||t.down);} finally{setBusy(false);}
  };
  const uploadConsultReceipt = async e => { const f=e.target.files?.[0]; e.target.value=''; if(!f||!consultPayment)return; setReceiptBusy(true); try { const r=await korganApi.uploadConsultationReceipt(consultPayment.order_id,f); setChat(x=>[...x,{role:'ai',text:r.answer,sources:r.sources||[]}]); setConsultPayment(null); } catch(err){setNotice(err?.message||t.down);} finally{setReceiptBusy(false);} };

  const finishDocument = async r => { setDocumentResult(r); setDocPayment(null); setActiveCase(x=>x?{...x,status:r.status,title:r.title,has_document:true,filing_ready:r.filing_ready,release_status:r.release_status,quality_score:r.quality_score}:x); await refreshCases(); setScreen('ready'); };
  const generateDocument = async () => { if(!activeCase||busy)return; setBusy(true);setNotice(''); try{const r=await korganApi.generateDocument(activeCase.id,activeCase.document_type,activeCase.language||language); if(r.payment_required){setDocPayment(r.payment);setScreen('payment');}else await finishDocument(r);}catch(e){setNotice(e?.message||t.down);}finally{setBusy(false);} };
  const uploadDocReceipt = async e => { const f=e.target.files?.[0];e.target.value='';if(!f||!docPayment)return;setReceiptBusy(true);setNotice('');try{const r=await korganApi.uploadDocumentReceipt(docPayment.order_id,f);await finishDocument(r);}catch(err){setNotice(err?.message||t.down);}finally{setReceiptBusy(false);} };
  const retryPaidDocument = async () => { if(!docPayment?.order_id)return;setBusy(true);try{const r=await korganApi.retryPaidDocument(docPayment.order_id);await finishDocument(r);}catch(e){setNotice(e?.message||t.paidRetry);}finally{setBusy(false);} };
  const getExisting = async () => { if(!activeCase)return;setBusy(true);try{const r=await korganApi.getDocument(activeCase.id);setDocumentResult(r);setScreen('ready');}catch(e){setNotice(e?.message||t.down);}finally{setBusy(false);} };
  const deleteCase = async () => { if(!activeCase)return;setBusy(true);try{await korganApi.deleteCase(activeCase.id);setActiveCase(null);await refreshCases();setScreen('cases');}catch(e){setNotice(e?.message||t.down);}finally{setBusy(false);} };

  const filtered = useMemo(() => DOCS.filter(d => d[language].join(' ').toLowerCase().includes(query.toLowerCase())), [query, language]);
  const Header = ({title,back='home'}) => <header className="subbar"><button className="icon-btn" onClick={()=>setScreen(back)}><ArrowLeft size={20}/></button><strong>{title}</strong><span className="header-spacer"/></header>;
  const Nav = () => <nav className="bottom-nav"><button onClick={()=>setScreen('home')}><Home size={20}/><span>{t.home}</span></button><button onClick={async()=>{await refreshCases();setScreen('cases');}}><FolderOpen size={20}/><span>{t.cases}</span></button><button onClick={()=>setScreen('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button><button onClick={()=>setScreen('profile')}><UserRound size={20}/><span>{t.profile}</span></button></nav>;
  const Notice = () => notice ? <div className="warning-note"><AlertTriangle size={17}/><span>{notice}</span></div> : null;

  if(!consent) return <div className="app-shell consent-shell"><main className="page consent-page"><div className="brand-mark large"><Scale size={28}/></div><div className="language-switch"><button className={language==='ru'?'active':''} onClick={()=>changeLanguage('ru')}>RU</button><button className={language==='kk'?'active':''} onClick={()=>changeLanguage('kk')}>KK</button></div><h1>{t.consentTitle}</h1><section className="privacy-card static"><ShieldCheck size={22}/><div><strong>KORGAN Legal AI</strong><p>{t.consentText}</p></div></section><section className="privacy-card static"><LockKeyhole size={22}/><div><strong>Privacy</strong><p>AES-256-GCM · Telegram initData · fail-closed</p></div></section><Notice/><button className="primary wide" disabled={busy} onClick={acceptTerms}><ShieldCheck size={18}/>{t.accept}</button></main></div>;

  if(screen==='documents') return <div className="app-shell"><Header title={t.selectDoc}/><main className="page"><div className="search"><Search size={18}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={t.search}/></div>{pricing?.document_payments_enabled&&<div className="price-note"><CreditCard size={16}/><span>{money(pricing.document_price_kzt)} · AI receipt verification</span></div>}<div className="list-card">{filtered.map(d=>{const I=d.icon;return <button className="list-row" key={d.id} onClick={()=>{setSelectedDoc(d.id);setScreen('new-case')}}><span className="row-icon"><I size={20}/></span><span><strong>{d[language][0]}</strong><small>{d[language][1]}</small></span><ChevronRight size={18}/></button>})}</div></main><Nav/></div>;
  if(screen==='new-case') return <div className="app-shell"><Header title={t.newCase} back="documents"/><main className="page"><h1>{docName(selectedDoc,language)}</h1><p>{t.analysisSub}</p><textarea className="case-input" value={description} onChange={e=>setDescription(e.target.value)} placeholder={t.describeHint}/><Notice/><button className="primary wide" disabled={busy||!description.trim()} onClick={createCase}>{busy?<LoaderCircle className="spin"/>:<Sparkles size={18}/>} {t.create}</button></main></div>;
  if(screen==='cases') return <div className="app-shell"><Header title={t.myCases}/><main className="page"><Notice/>{cases.map(c=><button className="case-list-item" key={c.id} onClick={()=>openCase(c)}><div className="case-badge"><Scale size={20}/></div><div><strong>{c.title||docName(c.document_type,language)}</strong><small>{c.id} · {c.materials_count||0} · {c.has_document?'DOCX':''}</small></div><ChevronRight size={18}/></button>)}<button className="primary wide" onClick={()=>setScreen('documents')}>{t.docs}</button></main><Nav/></div>;
  if(screen==='case'&&activeCase) return <div className="app-shell"><Header title={activeCase.id} back="cases"/><main className="page"><section className="analysis-card"><span className="section-kicker">{docName(activeCase.document_type,language)}</span><h2>{activeCase.title||t.analysis}</h2><p>{activeCase.description}</p><div className="fact"><span>{t.files}</span><strong>{activeCase.materials_count||0}</strong></div>{typeof activeCase.quality_score==='number'&&<div className="fact"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}</section><Notice/><label className="secondary wide"><Paperclip size={18}/>{t.upload}<input className="hidden-input" multiple type="file" accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.webp" onChange={uploadMaterials}/></label><button className="secondary wide" onClick={()=>setScreen('chat')}><MessageCircle size={18}/>{t.ask}</button>{activeCase.has_document&&<button className="secondary wide" onClick={getExisting}><Download size={18}/>{t.download}</button>}<button className="primary wide" disabled={busy} onClick={generateDocument}>{busy?<LoaderCircle className="spin" size={18}/>:<FileText size={18}/>} {busy?t.generating:`${t.generate}${pricing?.document_payments_enabled?` · ${money(pricing.document_price_kzt)}`:''}`}</button><button className="secondary danger wide" onClick={deleteCase}><Trash2 size={18}/>{t.delete}</button></main><Nav/></div>;
  if(screen==='chat') return <div className="app-shell chat-shell"><Header title={activeCase?`${t.lawyer} · ${activeCase.id}`:t.lawyer}/><main className="chat-page">{freeRemaining!==null&&<div className="quota-note"><BadgeCheck size={15}/>{t.free}: <strong>{freeRemaining}</strong></div>}<div className="messages">{chat.map((m,i)=><div key={i} className={`message-wrap ${m.role==='user'?'user-wrap':'ai-wrap'}`}><div className={`bubble ${m.role==='user'?'user':'ai'}`}>{m.text}</div>{m.sources?.length>0&&<div className="source-list"><span>{t.sources}</span>{m.sources.map((s,j)=><a key={j} href={s} target="_blank" rel="noreferrer">{s}</a>)}</div>}</div>)}</div>{consultPayment&&<section className="payment-card"><h3>{t.consultationLimit}</h3><div className="payment-amount">{money(consultPayment.amount_kzt)}</div><button className="primary wide" onClick={()=>window.open(consultPayment.kaspi_url,'_blank')}><CreditCard size={18}/>{t.pay}<ExternalLink size={15}/></button><label className="secondary wide"><Paperclip size={18}/>{receiptBusy?t.receiptCheck:t.receipt}<input className="hidden-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={uploadConsultReceipt}/></label></section>}<Notice/><div className="composer"><input value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')sendMessage()}} disabled={Boolean(consultPayment)} placeholder={t.send}/><button onClick={sendMessage} disabled={busy||Boolean(consultPayment)}><Send size={19}/></button></div></main><Nav/></div>;
  if(screen==='payment'&&docPayment) return <div className="app-shell"><Header title={t.payment} back="case"/><main className="page payment-page"><div className="payment-stage-icon"><Banknote size={38}/></div><h1>{t.payment}</h1><p>{t.paymentText}</p><div className="payment-amount centered">{money(docPayment.amount_kzt)}</div><section className="analysis-card"><ShieldCheck size={22}/><p>{t.paySecurity}</p></section><Notice/><button className="primary wide" onClick={()=>window.open(docPayment.kaspi_url,'_blank')}><CreditCard size={18}/>{t.pay}<ExternalLink size={15}/></button><label className="secondary wide"><Paperclip size={18}/>{receiptBusy?t.receiptCheck:t.receipt}<input className="hidden-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={uploadDocReceipt}/></label>{docPayment.status==='approved'&&<button className="secondary wide" onClick={retryPaidDocument}><RefreshCw size={18}/>{t.paidRetry}</button>}</main></div>;
  if(screen==='ready'&&documentResult) return <div className="app-shell"><Header title={t.ready} back="case"/><main className="page ready-page"><div className={`success-ring ${documentResult.filing_ready?'':'preliminary-ring'}`}>{documentResult.filing_ready?<CheckCircle2 size={48}/>:<ShieldAlert size={44}/>}</div><span className={`release-badge ${documentResult.filing_ready?'ready':'preliminary'}`}>{documentResult.filing_ready?t.filingReady:t.preliminary}</span><h1>{documentResult.title||t.ready}</h1><div className="release-grid"><div><span>{t.quality}</span><strong>{typeof documentResult.quality_score==='number'?`${documentResult.quality_score}/10`:'—'}</strong></div><div><span>{t.status}</span><strong>{documentResult.release_status}</strong></div></div><button className="primary wide" onClick={()=>downloadBase64(documentResult.document_base64,documentResult.filename)}><Download size={18}/>{t.download}</button><button className="lawyer-btn wide" onClick={()=>window.open(LAWYER_URL,'_blank')}><ShieldCheck size={18}/>{t.live}</button></main></div>;
  if(screen==='profile') return <div className="app-shell"><Header title={t.profile}/><main className="page"><section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>KORGAN</h2><p>{online?t.connected:t.down}</p></div><BadgeCheck size={18}/></section><section className="settings-card"><div className="settings-row"><Languages size={20}/><div><strong>{t.lang}</strong></div><div className="language-switch compact"><button className={language==='ru'?'active':''} onClick={()=>changeLanguage('ru')}>RU</button><button className={language==='kk'?'active':''} onClick={()=>changeLanguage('kk')}>KK</button></div></div></section><button className="secondary wide" onClick={()=>window.open(LAWYER_URL,'_blank')}><ShieldCheck size={18}/>{t.live}</button><button className="secondary wide" onClick={()=>window.open(SUPPORT_URL,'_blank')}><Headphones size={18}/>{t.support}</button><button className="secondary danger wide" onClick={async()=>{setBusy(true);try{await korganApi.deleteMyData();clearAllLocalData();setConsent(false);setCases([]);}finally{setBusy(false)}}}><Trash2 size={18}/>{t.deleteAll}</button></main><Nav/></div>;

  return <div className="app-shell"><main className="page home-page"><div className="hero"><div className="brand-mark"><Scale size={26}/></div><span className="section-kicker">KORGANZAN.Ai</span><h1>{t.hero}</h1><p>{t.heroSub}</p><div className={`connection-note ${online?'':'offline'}`}><span className={online?'dot on':'dot'}/>{online?t.connected:t.down}</div></div><Notice/><div className="home-actions"><button className="primary wide" onClick={()=>setScreen('chat')}><MessageCircle size={19}/>{t.consult}</button><button className="secondary wide" onClick={()=>setScreen('documents')}><FileText size={19}/>{t.docs}</button><button className="secondary wide" onClick={async()=>{await refreshCases();setScreen('cases')}}><FolderOpen size={19}/>{t.myCases}</button></div><section className="analysis-card"><Sparkles size={22}/><h2>{t.analysis}</h2><p>{t.analysisSub}</p></section></main><Nav/></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
