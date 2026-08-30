import { readFileSync, writeFileSync } from 'node:fs';

function replaceRequired(text, from, to, label) {
  const index = text.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to patch build.`);
  return text.slice(0, index) + to + text.slice(index + from.length);
}

const mainFile = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(mainFile, 'utf8');
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

// Quality scoring and release diagnostics are internal only.
source = replaceRequired(
  source,
  ", release_status: result.release_status, quality_score: result.quality_score }));",
  ", release_status: result.release_status }));",
  'generated document client quality state',
);
source = replaceRequired(
  source,
  "{typeof activeCase.quality_score === 'number' && <div className=\"fact\"><span>{t.quality}</span><strong>{activeCase.quality_score}/10</strong></div>}",
  "",
  'case quality score',
);
source = replaceRequired(
  source,
  "<div className=\"release-grid\"><div><span>{t.quality}</span><strong>{typeof documentResult?.quality_score === 'number' ? `${documentResult.quality_score}/10` : '—'}</strong></div><div><span>{t.check}</span><strong>{documentResult?.release_status || '—'}</strong></div></div>",
  "<div className=\"release-grid\" style={{gridTemplateColumns:'1fr'}}><div><span>{t.check}</span><strong>{documentResult?.release_status || '—'}</strong></div></div>",
  'ready screen quality score',
);
source = replaceRequired(
  source,
  "{(documentResult?.verification_notes?.length > 0 || documentResult?.quality_issues?.length > 0) && <div className=\"warning-note left-note\"><AlertTriangle size={17}/><span>{[...(documentResult.verification_notes || []), ...(documentResult.quality_issues || [])].filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</span></div>}",
  "{documentResult?.verification_notes?.length > 0 && <div className=\"warning-note left-note\"><AlertTriangle size={17}/><span>{(documentResult.verification_notes || []).filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</span></div>}",
  'ready screen internal quality issues',
);
source = replaceRequired(
  source,
  "<div className=\"fact\"><span>{t.quality}</span><strong>{runtimeInfo?.word_quality_target || '—'}</strong></div>",
  "",
  'profile quality target',
);
source = replaceRequired(
  source,
  "{activeCase.verification_status && <div className=\"fact\"><span>{t.check}</span><strong>{activeCase.filing_ready ? t.verified : t.needsCheck}</strong></div>}",
  "",
  'case release verification status',
);

// Document-specific consultation goes to the KORGAN WhatsApp line with this case context.
source = replaceRequired(
  source,
  '<button className="secondary wide" onClick={() => go(\'chat\')}><MessageCircle size={18}/>{t.consultCase}</button>',
  `<button className="secondary wide" onClick={() => {
    const kind = language === 'kk'
      ? activeCase.document_type === 'claim' ? 'Талап бойынша кеңес'
        : activeCase.document_type === 'contract' ? 'Шарт бойынша кеңес'
        : activeCase.document_type === 'response' ? 'Талапқа пікір бойынша кеңес'
        : activeCase.document_type === 'pretrial' ? 'Сотқа дейінгі талап бойынша кеңес'
        : activeCase.document_type === 'pretrial_response' ? 'Талапқа жауап бойынша кеңес'
        : 'Құжат бойынша кеңес'
      : activeCase.document_type === 'claim' ? 'Консультация по иску'
        : activeCase.document_type === 'contract' ? 'Консультация по договору'
        : activeCase.document_type === 'response' ? 'Консультация по отзыву на иск'
        : activeCase.document_type === 'pretrial' ? 'Консультация по претензии'
        : activeCase.document_type === 'pretrial_response' ? 'Консультация по ответу на претензию'
        : 'Консультация по документу';
    const documentTitle = activeCase.title || title;
    const text = language === 'kk'
      ? 'Сәлеметсіз бе. ' + kind + ' қажет.\\n\\nҚұжат: ' + documentTitle + '\\nІс нөмірі: ' + activeCase.id + (activeCase.has_document ? '\\nҚұжат KORGAN жүйесінде дайын және осы істе сақталған.' : '')
      : 'Здравствуйте. Нужна ' + kind.toLowerCase() + '.\\n\\nДокумент: ' + documentTitle + '\\nНомер дела: ' + activeCase.id + (activeCase.has_document ? '\\nДокумент уже подготовлен и сохранён в KORGAN в этом деле.' : '');
    const url = WHATSAPP_URL + '?text=' + encodeURIComponent(text);
    const tg = window.Telegram?.WebApp;
    if (tg?.openLink) tg.openLink(url); else window.open(url, '_blank', 'noopener,noreferrer');
  }}><MessageCircle size={18}/>{language === 'kk'
    ? activeCase.document_type === 'claim' ? 'Талап бойынша кеңес'
      : activeCase.document_type === 'contract' ? 'Шарт бойынша кеңес'
      : activeCase.document_type === 'response' ? 'Талапқа пікір бойынша кеңес'
      : activeCase.document_type === 'pretrial' ? 'Сотқа дейінгі талап бойынша кеңес'
      : activeCase.document_type === 'pretrial_response' ? 'Талапқа жауап бойынша кеңес'
      : 'Құжат бойынша кеңес'
    : activeCase.document_type === 'claim' ? 'Консультация по иску'
      : activeCase.document_type === 'contract' ? 'Консультация по договору'
      : activeCase.document_type === 'response' ? 'Консультация по отзыву на иск'
      : activeCase.document_type === 'pretrial' ? 'Консультация по претензии'
      : activeCase.document_type === 'pretrial_response' ? 'Консультация по ответу на претензию'
      : 'Консультация по документу'}</button>`,
  'document consultation action',
);

// The customer-ready screen must never expose preliminary/release/quality internals.
const readyStartMarker = "  if (screen === 'ready')";
const readyEndMarker = "\n\n  if (screen === 'cases')";
const readyStart = source.indexOf(readyStartMarker);
const readyEnd = source.indexOf(readyEndMarker, readyStart);
if (readyStart < 0 || readyEnd < 0) {
  throw new Error('KORGAN ready screen block not found; refusing to patch build.');
}
const readyBlock = `  if (screen === 'ready') return <div className="app-shell"><Header title={t.docReady} back="case"/><main className="page ready-page"><div className="success-ring"><CheckCircle2 size={48}/></div><h1>{documentResult?.title || t.docReady}</h1><div className="document-preview"><div className="paper-lines"><b>{documentResult?.title || 'KORGAN LEGAL AI'}</b><span/><span/><span/><span/><span/></div></div><button className="primary wide" disabled={!documentResult?.document_base64} onClick={() => downloadBase64(documentResult.document_base64, documentResult.filename)}><Download size={18}/>{t.download}</button></main></div>;`;
source = source.slice(0, readyStart) + readyBlock + source.slice(readyEnd);

// Keep payment verification wording concise and customer-facing.
source = replaceRequired(
  source,
  "manualCheck: 'Ручное подтверждение'",
  "manualCheck: 'Проверка оплаты'",
  'payment verification title',
);
source = replaceRequired(
  source,
  "manualCheck: 'Қолмен растау'",
  "manualCheck: 'Төлемді тексеру'",
  'payment verification title kk',
);
source = replaceRequired(
  source,
  "<h2>{t.manualCheck}</h2>",
  "<h2>{language === 'kk' ? 'Чекті жүктегеннен кейін әкімші төлемді тексеріп, құжатты дайындауды растайды.' : 'После загрузки чека администратор проверит оплату и подтвердит подготовку документа.'}</h2>",
  'payment verification customer copy',
);
source = replaceRequired(
  source,
  "<p>{t.manualCheckSub}</p>",
  "",
  'payment verification explanatory text',
);

// Human-lawyer wording: there are no "live lawyers" in customer copy.
source = source
  .replaceAll('Проверка живым юристом', 'Персональный юрист')
  .replaceAll('живым юристом', 'персональным юристом')
  .replaceAll('Живой юрист', 'Персональный юрист')
  .replaceAll('живой юрист', 'персональный юрист')
  .replaceAll('Тірі заңгердің тексеруі', 'Жеке заңгер')
  .replaceAll('Тірі заңгер', 'Жеке заңгер')
  .replaceAll('тірі заңгер', 'жеке заңгер');

// Payment flow is intentionally not rewritten at build time. The React source
// owns the manual-admin states: pending_receipt -> awaiting_admin -> approved.
writeFileSync(mainFile, source, 'utf8');

// The live API now requires manual administrator confirmation for documents.
// Keep the frontend readiness gate aligned with that production contract.
const apiFile = new URL('../src/korganApi.js', import.meta.url);
let apiSource = readFileSync(apiFile, 'utf8');
apiSource = replaceRequired(
  apiSource,
  "(parity?.document_payments_enabled && parity?.document_manual_confirmation !== false)",
  "(parity?.document_payments_enabled && parity?.document_manual_confirmation !== true)",
  'manual payment parity requirement',
);
writeFileSync(apiFile, apiSource, 'utf8');
