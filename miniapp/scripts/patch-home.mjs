import { readFileSync, writeFileSync } from 'node:fs';

const file = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(file, 'utf8');
const startMarker = '  return <div className="app-shell"><header className="topbar">';
const endMarker = '\n}\n\ncreateRoot(document.getElementById(\'root\')).render(<App/>);';
const start = source.lastIndexOf(startMarker);
const end = source.indexOf(endMarker, start);

if (start < 0 || end < 0) {
  throw new Error('KORGAN home return block not found; refusing to patch build.');
}

const home = `  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div><div className={\`top-status \${connection}\`}><span/>{connection === 'ok' ? t.connected : connection === 'down' ? t.down : t.connecting}</div></header><main className="home-page workspace-home native-home"><ConnectionBanner/><section className="native-home-intro"><div className={\`native-home-status \${backendOk ? 'ok' : 'down'}\`} aria-label={backendOk ? t.connected : t.down}><span/></div></section><section className="native-service-hub"><div className="action-grid workspace-actions native-service-grid"><button className="action-card home-ai-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><div className="action-copy"><h2>{t.lawyer}</h2><p>{language === 'kk' ? 'Құқықтық талдау және іс бойынша жауаптар' : 'Правовой анализ и ответы по делу'}</p></div><span className="home-card-arrow"><ChevronRight size={16}/></span></button><button className="action-card home-document-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><div className="action-copy"><h2>{t.prepare}</h2><p>{language === 'kk' ? 'Талаптар, шағымдар, өтініштер және шарттар' : 'Иски, жалобы, заявления и договоры'}</p></div><span className="home-card-arrow"><ChevronRight size={16}/></span></button><button className="action-card home-cases-card" onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><div className="action-icon case"><FolderOpen/></div><div className="action-copy"><h2>{t.myCases}</h2><p>{language === 'kk' ? 'Материалдар, кеңестер және дайын құжаттар' : 'Материалы, консультации и готовые документы'}</p></div><span className="home-card-arrow"><ChevronRight size={16}/></span></button><button className="action-card home-privacy-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><div className="action-copy"><h2>{t.privacy}</h2><p>{t.privacySub}</p></div><span className="home-card-arrow"><ChevronRight size={16}/></span></button><button className="action-card native-help-card" onClick={() => go('help')}><div className="action-icon help"><CircleHelp/></div><div className="action-copy"><h2>{t.help}</h2><p>{language === 'kk' ? 'Қолдау және сервис туралы ақпарат' : 'Поддержка и информация о сервисе'}</p></div></button></div></section></main><BottomNav/></div>;`;

source = source.slice(0, start) + home + source.slice(end);

const chatAnchor = 'if (screen === \'chat\') return <div className="app-shell chat-shell">';
const chatStart = source.indexOf(chatAnchor);
const chatMain = '<main className="chat-page">';
const chatMainStart = chatStart >= 0 ? source.indexOf(chatMain, chatStart) : -1;
if (chatStart < 0 || chatMainStart < 0) {
  throw new Error('KORGAN chat block not found; refusing to patch build.');
}
const chatInsertAt = chatMainStart + chatMain.length;
const chatTitle = `<section className="chat-product-title"><h1>{language === 'kk' ? 'Сіздің заңгерлік AI-көмекшіңіз' : 'Ваш юридический AI-помощник'}</h1></section>`;
if (!source.includes('className="chat-product-title"')) {
  source = source.slice(0, chatInsertAt) + chatTitle + source.slice(chatInsertAt);
}

// Payment flow is intentionally NOT rewritten at build time.
// The React source keeps the active PDF/image receipt upload button.
// Backend extracts receipt.kaspi.kz from the uploaded fiscal receipt and verifies
// amount, merchant, fiscal identifiers, freshness and uniqueness through Kaspi OFD.
writeFileSync(file, source, 'utf8');
