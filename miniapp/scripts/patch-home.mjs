import { readFileSync, writeFileSync } from 'node:fs';

const file = new URL('../src/main.jsx', import.meta.url);
const source = readFileSync(file, 'utf8');
const startMarker = '  return <div className="app-shell"><header className="topbar">';
const endMarker = '\n}\n\ncreateRoot(document.getElementById(\'root\')).render(<App/>);';
const start = source.lastIndexOf(startMarker);
const end = source.indexOf(endMarker, start);

if (start < 0 || end < 0) {
  throw new Error('KORGAN home return block not found; refusing to patch build.');
}

const home = `  return <div className="app-shell"><header className="topbar"><div className="brand-mark"><Scale size={18}/></div><div className="brand"><strong>KORGAN</strong><span>Legal AI</span></div><div className={\`top-status \${connection}\`}><span/>{connection === 'ok' ? t.connected : connection === 'down' ? t.down : t.connecting}</div></header><main className="home-page workspace-home native-home"><ConnectionBanner/><section className="native-home-intro"><div className={\`native-home-status \${backendOk ? 'ok' : 'down'}\`} aria-label={backendOk ? t.connected : t.down}><span/></div><h1>{language === 'kk' ? 'Сіздің заңгерлік AI-көмекшіңіз' : 'Ваш юридический AI-помощник'}</h1><p>{language === 'kk' ? 'Кеңес, құжаттар және істермен жұмыс бір қолданбада.' : 'Консультации, документы и работа с делами в одном приложении.'}</p></section><section className="native-service-hub"><div className="action-grid workspace-actions native-service-grid"><button className="action-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><div className="action-copy"><h2>{t.consultation}</h2><p>{t.consultationSub}</p></div></button><button className="action-card" onClick={() => go('documents')}><div className="action-icon document"><FileText/></div><div className="action-copy"><h2>{t.prepare}</h2><p>{t.prepareSub}</p></div></button><button className="action-card" onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><div className="action-icon case"><FolderOpen/></div><div className="action-copy"><h2>{t.myCases}</h2><p>{t.casesSub}</p></div></button><button className="action-card" onClick={() => go('profile')}><div className="action-icon review"><ShieldCheck/></div><div className="action-copy"><h2>{t.privacy}</h2><p>{t.privacySub}</p></div></button><button className="action-card native-help-card" onClick={() => go('help')}><div className="action-icon help"><CircleHelp/></div><div className="action-copy"><h2>{t.help}</h2><p>{language === 'kk' ? 'Қолдау және сервис туралы ақпарат' : 'Поддержка и информация о сервисе'}</p></div></button></div></section></main><BottomNav/></div>;`;

writeFileSync(file, source.slice(0, start) + home + source.slice(end), 'utf8');
