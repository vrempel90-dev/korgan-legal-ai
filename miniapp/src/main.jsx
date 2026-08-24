import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Scale, MessageCircle, FileText, FolderOpen, ShieldCheck, Home, Bell, UserRound, ArrowRight } from 'lucide-react';
import './styles.css';

const actions = [
  { id: 'consult', title: 'Консультация', text: 'Задайте вопрос AI-юристу', icon: MessageCircle },
  { id: 'document', title: 'Подготовить документ', text: 'Иск, жалоба, договор и другие документы', icon: FileText },
  { id: 'case', title: 'Моё дело', text: 'Ваши дела, документы и история', icon: FolderOpen },
  { id: 'review', title: 'Проверка юристом', text: 'Передайте документ живому юристу', icon: ShieldCheck },
];

function App() {
  const [active, setActive] = useState('home');

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (!tg) return;
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.('#06152f');
    tg.setBackgroundColor?.('#f5f7fb');
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><Scale size={18} /></div>
        <div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div>
      </header>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <div className="online"><span /> Онлайн</div>
            <h1>Ваш AI-юрист</h1>
            <p>Юридическая помощь, документы и сопровождение дела в одном приложении.</p>
            <button onClick={() => setActive('consult')}>Начать консультацию <ArrowRight size={17} /></button>
          </div>
          <div className="hero-orb"><Scale size={52} /></div>
        </section>

        <section className="action-grid">
          {actions.map(({ id, title, text, icon: Icon }) => (
            <button className="action-card" key={id} onClick={() => setActive(id)}>
              <div className={`action-icon ${id}`}><Icon size={23} /></div>
              <h2>{title}</h2>
              <p>{text}</p>
            </button>
          ))}
        </section>

        <section className="privacy-card">
          <div className="privacy-icon"><ShieldCheck size={19} /></div>
          <div><strong>Конфиденциальность</strong><p>Данные защищены и не передаются третьим лицам.</p></div>
          <ArrowRight size={18} />
        </section>

        {active !== 'home' && (
          <section className="prototype-note">
            <strong>Раздел «{actions.find(a => a.id === active)?.title}»</strong>
            <span>Экран уже заложен в навигацию. Следующим шагом подключим полноценный пользовательский сценарий.</span>
          </section>
        )}
      </main>

      <nav className="bottom-nav">
        <button className={active === 'home' ? 'active' : ''} onClick={() => setActive('home')}><Home size={20}/><span>Главная</span></button>
        <button onClick={() => setActive('case')}><FolderOpen size={20}/><span>Дела</span></button>
        <button onClick={() => setActive('consult')}><MessageCircle size={20}/><span>Сообщения</span></button>
        <button><Bell size={20}/><span>Уведомления</span></button>
        <button><UserRound size={20}/><span>Профиль</span></button>
      </nav>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
