import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home, Bell,
  UserRound, ArrowRight, ArrowLeft, Search, ChevronRight, CheckCircle2,
  BriefcaseBusiness, ShoppingCart, Building2, Landmark, HandCoins, Send,
  Download, Eye, LockKeyhole, Sparkles
} from 'lucide-react';
import './styles.css';
import { isBackendConnected } from './korganApi';

const documents = [
  { id: 'claim', title: 'Исковое заявление', subtitle: 'Подготовка иска в суд', icon: Scale },
  { id: 'debt', title: 'Взыскание долга', subtitle: 'Договор, расписка, поставка', icon: HandCoins },
  { id: 'consumer', title: 'Защита прав потребителей', subtitle: 'Возврат товара, услуги, компенсация', icon: ShoppingCart },
  { id: 'housing', title: 'Жилищные споры', subtitle: 'Выселение, вселение, жильё', icon: Building2 },
  { id: 'labor', title: 'Трудовые споры', subtitle: 'Увольнение, зарплата, восстановление', icon: BriefcaseBusiness },
  { id: 'admin', title: 'Административная жалоба', subtitle: 'Действия госорганов и должностных лиц', icon: Landmark },
];

const demoCase = {
  id: 'KOR-2026-00123',
  title: 'Взыскание задолженности по договору поставки',
  debt: '8 500 000 ₸',
  penalty: '782 000 ₸',
  status: 'AI-анализ готов',
};

function App() {
  const [screen, setScreen] = useState('home');
  const [caseText, setCaseText] = useState('');
  const [query, setQuery] = useState('');
  const [chat, setChat] = useState([
    { from: 'ai', text: 'Я помогу подготовить юридическую позицию. Опишите ситуацию своими словами — даты, суммы и документы я выделю сам.' },
  ]);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (!tg) return;
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.('#06152f');
    tg.setBackgroundColor?.('#f4f7fb');
  }, []);

  const filteredDocuments = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? documents.filter(d => `${d.title} ${d.subtitle}`.toLowerCase().includes(q)) : documents;
  }, [query]);

  const go = (next) => {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light');
    setScreen(next);
  };

  const sendMessage = () => {
    const text = message.trim();
    if (!text) return;
    setChat(prev => [...prev, { from: 'user', text }, { from: 'ai', text: 'Принял. Этот экран уже готов к подключению существующего KORGAN AI через отдельный API-адаптер.' }]);
    setMessage('');
  };

  const Header = ({ title, back = 'home' }) => (
    <header className="subbar">
      <button className="icon-btn" onClick={() => go(back)}><ArrowLeft size={20}/></button>
      <strong>{title}</strong>
      <span className="header-spacer" />
    </header>
  );

  const BottomNav = () => (
    <nav className="bottom-nav">
      <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>Главная</span></button>
      <button className={screen === 'cases' ? 'active' : ''} onClick={() => go('cases')}><FolderOpen size={20}/><span>Дела</span></button>
      <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>AI-юрист</span></button>
      <button><Bell size={20}/><span>Уведомления</span></button>
      <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>Профиль</span></button>
    </nav>
  );

  if (screen === 'documents') return (
    <div className="app-shell"><Header title="Выбор документа" />
      <main className="page">
        <div className="search"><Search size={18}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск документа"/></div>
        <div className="section-kicker">Популярные документы</div>
        <div className="list-card">
          {filteredDocuments.map(({ id, title, subtitle, icon: Icon }) => (
            <button className="list-row" key={id} onClick={() => go('new-case')}>
              <span className="row-icon"><Icon size={20}/></span><span><strong>{title}</strong><small>{subtitle}</small></span><ChevronRight size={18}/>
            </button>
          ))}
        </div>
      </main><BottomNav /></div>
  );

  if (screen === 'new-case') return (
    <div className="app-shell"><Header title="Новое дело" back="documents" />
      <main className="page creation-page">
        <div className="progress"><span className="done">1</span><i/><span>2</span><i/><span>3</span><i/><span>4</span></div>
        <div className="big-title"><span className="eyebrow">Шаг 1 из 4</span><h1>Расскажите, что произошло</h1><p>Не заполняйте длинную анкету. AI сам извлечёт стороны, суммы, даты и задаст только недостающие вопросы.</p></div>
        <textarea className="case-input" value={caseText} onChange={e => setCaseText(e.target.value)} maxLength={3000} placeholder="Например: мы поставили товар на 8 500 000 ₸, покупатель должен был оплатить до 30 марта, но не оплатил..." />
        <div className="input-meta"><Sparkles size={17}/> Чем подробнее описание, тем точнее документ <span>{caseText.length}/3000</span></div>
        <button className="primary wide" disabled={!caseText.trim()} onClick={() => go('case')}>Продолжить <ArrowRight size={18}/></button>
      </main></div>
  );

  if (screen === 'case') return (
    <div className="app-shell"><Header title={`Дело ${demoCase.id}`} />
      <main className="page">
        <section className="status-card"><div><span className="section-kicker">Статус дела</span><h2>{demoCase.status}</h2></div><span className="pill success">Готово</span></section>
        <section className="timeline"><div className="step complete"><CheckCircle2/>Создано</div><div className="step complete"><CheckCircle2/>Анализ</div><div className="step current"><span>3</span>Документ</div><div className="step"><span>4</span>Завершено</div></section>
        <section className="analysis-card"><div className="card-head"><div><span className="section-kicker">AI-анализ дела</span><h2>{demoCase.title}</h2></div><Sparkles size={22}/></div>
          <div className="fact"><span>Основной долг</span><strong>{demoCase.debt}</strong></div>
          <div className="fact"><span>Договорная неустойка</span><strong>{demoCase.penalty}</strong></div>
          <div className="fact"><span>Категория</span><strong>Договор поставки</strong></div>
        </section>
        <button className="primary wide" onClick={() => go('chat')}>Продолжить с AI-юристом <MessageCircle size={18}/></button>
        <button className="secondary wide" onClick={() => go('ready')}>Показать демо готового документа</button>
      </main><BottomNav /></div>
  );

  if (screen === 'chat') return (
    <div className="app-shell chat-shell"><Header title="Чат с AI-юристом" />
      <main className="chat-page">
        <div className="connection-note"><span className={isBackendConnected() ? 'dot on' : 'dot'} /> {isBackendConnected() ? 'KORGAN backend подключён' : 'UI-режим: production backend не затрагивается'}</div>
        <div className="messages">{chat.map((m, i) => <div key={i} className={`bubble ${m.from}`}>{m.text}</div>)}</div>
        <div className="composer"><input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendMessage()} placeholder="Напишите сообщение…"/><button onClick={sendMessage}><Send size={19}/></button></div>
      </main><BottomNav /></div>
  );

  if (screen === 'ready') return (
    <div className="app-shell"><Header title="Документ готов" back="case" />
      <main className="page ready-page">
        <div className="success-ring"><CheckCircle2 size={48}/></div><h1>Исковое заявление сформировано</h1><p>Документ готов к просмотру и дальнейшей проверке.</p>
        <div className="document-preview"><div className="paper-lines"><b>ИСКОВОЕ ЗАЯВЛЕНИЕ</b><span/><span/><span/><span/><span/></div></div>
        <button className="primary wide"><Eye size={18}/> Просмотреть документ</button>
        <button className="secondary wide"><Download size={18}/> Скачать DOCX</button>
        <button className="secondary wide"><Download size={18}/> Скачать PDF</button>
        <button className="lawyer-btn"><ShieldCheck size={18}/> Отправить юристу на проверку</button>
      </main></div>
  );

  if (screen === 'cases') return (
    <div className="app-shell"><Header title="Мои дела" />
      <main className="page"><section className="case-list-item" onClick={() => go('case')}><div className="case-badge"><Scale size={20}/></div><div><strong>{demoCase.title}</strong><small>{demoCase.id} · {demoCase.status}</small></div><ChevronRight size={18}/></section>
      <button className="primary wide" onClick={() => go('documents')}>Создать новое дело</button></main><BottomNav /></div>
  );

  if (screen === 'profile') return (
    <div className="app-shell"><Header title="Профиль" />
      <main className="page"><section className="profile-card"><div className="avatar"><UserRound size={30}/></div><div><h2>Пользователь KORGAN</h2><p>Telegram Mini App</p></div></section><section className="privacy-card static"><LockKeyhole size={20}/><div><strong>Конфиденциальность</strong><p>Архитектура Mini App отделена от production-бота. Подключение данных будет выполняться через контролируемый API.</p></div></section></main><BottomNav /></div>
  );

  return (
    <div className="app-shell">
      <header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div></header>
      <main className="home-page">
        <section className="hero"><div className="hero-copy"><div className="online"><span/> Онлайн</div><h1>Ваш AI-юрист</h1><p>Юридическая помощь, документы и сопровождение дела в одном приложении.</p><button onClick={() => go('chat')}>Начать консультацию <ArrowRight size={17}/></button></div><div className="hero-orb"><Scale size={52}/></div></section>
        <section className="action-grid">
          <button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><h2>Консультация</h2><p>Задайте вопрос AI-юристу</p></button>
          <button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><h2>Подготовить документ</h2><p>Иск, жалоба, договор и другие документы</p></button>
          <button className="action-card" onClick={() => go('cases')}><div className="action-icon case"><FolderOpen/></div><h2>Моё дело</h2><p>Ваши дела, документы и история</p></button>
          <button className="action-card" onClick={() => go('ready')}><div className="action-icon review"><ShieldCheck/></div><h2>Проверка юристом</h2><p>Передайте документ живому юристу</p></button>
        </section>
        <section className="privacy-card"><div className="privacy-icon"><ShieldCheck size={19}/></div><div><strong>Конфиденциальность</strong><p>Данные защищены. Mini App подключается к KORGAN через отдельный безопасный слой.</p></div><ChevronRight size={18}/></section>
      </main><BottomNav />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App/>);
