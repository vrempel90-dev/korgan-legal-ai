import { readFileSync, writeFileSync } from 'node:fs';

function replaceRequired(text, from, to, label) {
  const index = text.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to patch build.`);
  return text.slice(0, index) + to + text.slice(index + from.length);
}

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

// Payment verification in production is based on the official fiscal QR URL.
// The payer identity is deliberately irrelevant: an individual, sole proprietor
// or company can pay. The backend still validates the merchant, amount, fiscal
// identity, time and receipt uniqueness before unlocking the service.
if (!source.includes("const [receiptUrl, setReceiptUrl]")) {
  source = replaceRequired(
    source,
    "  const [receiptBusy, setReceiptBusy] = useState(false);",
    "  const [receiptBusy, setReceiptBusy] = useState(false);\n  const [receiptUrl, setReceiptUrl] = useState('');",
    'receipt URL state',
  );
}

source = replaceRequired(
  source,
  "paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите одну консультацию через Kaspi и загрузите полный чек. После автоматической проверки ответ продолжится по этому же вопросу.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек', checkingReceipt: 'Проверяю чек…'",
  "paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите консультацию и вставьте ссылку receipt.kaspi.kz из QR фискального чека. Плательщик может быть физлицом, ИП или ТОО.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Проверить оплату', checkingReceipt: 'Проверяю оплату…'",
  'Russian consultation payment copy',
);
source = replaceRequired(
  source,
  "documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.'",
  "documentPayment: 'Оплата документа', documentPaymentText: 'Оплатите документ и вставьте ссылку receipt.kaspi.kz из QR фискального чека. Физлицо, ИП и ТОО проходят одну и ту же автоматическую проверку.'",
  'Russian document payment copy',
);
source = replaceRequired(
  source,
  "paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Kaspi арқылы бір кеңес ақысын төлеп, толық чекті жүктеңіз. Автоматты тексеруден кейін осы сұрақ бойынша жауап жалғасады.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу', checkingReceipt: 'Чек тексерілуде…'",
  "paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Кеңес ақысын төлеп, фискалдық чектегі QR ашатын receipt.kaspi.kz сілтемесін енгізіңіз. Төлеуші жеке тұлға, ЖК немесе ЖШС болуы мүмкін.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Төлемді тексеру', checkingReceipt: 'Төлем тексерілуде…'",
  'Kazakh consultation payment copy',
);
source = replaceRequired(
  source,
  "documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.'",
  "documentPayment: 'Құжат төлемі', documentPaymentText: 'Құжат ақысын төлеп, фискалдық чектегі QR ашатын receipt.kaspi.kz сілтемесін енгізіңіз. Жеке тұлға, ЖК және ЖШС үшін тексеру бірдей.'",
  'Kazakh document payment copy',
);

const oldConsultHandler = `  const uploadConsultReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !consultPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, file); appendAnswer(result); setConsultPayment(null); }
    catch (error) { if (error?.status === 503) { setConsultPayment(prev => ({ ...prev, paidPending: true })); setNotice(t.paidSaved); } else setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };`;
const newConsultHandler = `  const uploadConsultReceipt = async () => {
    const value = receiptUrl.trim(); if (!value || !consultPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, value); appendAnswer(result); setReceiptUrl(''); setConsultPayment(null); }
    catch (error) { if (error?.status === 503) { setConsultPayment(prev => ({ ...prev, paidPending: true })); setNotice(t.paidSaved); } else setNotice(error?.message || t.down); }
    finally { setReceiptBusy(false); }
  };`;
source = replaceRequired(source, oldConsultHandler, newConsultHandler, 'consultation OFD handler');

const oldDocHandler = `  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin); }
    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }
  };`;
const newDocHandler = `  const uploadDocReceipt = async () => {
    const value = receiptUrl.trim(); if (!value || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, value); setDocPayment(result.payment); setReceiptUrl(''); setNotice(result.message || t.paymentApproved); }
    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }
  };`;
source = replaceRequired(source, oldDocHandler, newDocHandler, 'document OFD handler');

const oldConsultUpload = `<label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadConsultReceipt}/></label>`;
const newConsultUpload = `<div className="search receipt-url-entry"><Link2 size={18}/><input type="url" inputMode="url" autoCapitalize="none" autoCorrect="off" value={receiptUrl} onChange={e => setReceiptUrl(e.target.value)} placeholder="https://receipt.kaspi.kz/..."/></div><button className="secondary wide" disabled={receiptBusy || !receiptUrl.trim()} onClick={uploadConsultReceipt}><ShieldCheck size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}</button>`;
source = replaceRequired(source, oldConsultUpload, newConsultUpload, 'consultation receipt input');

const oldDocUpload = `<label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadDocReceipt}/></label>`;
const newDocUpload = `<div className="search receipt-url-entry"><Link2 size={18}/><input type="url" inputMode="url" autoCapitalize="none" autoCorrect="off" value={receiptUrl} onChange={e => setReceiptUrl(e.target.value)} placeholder="https://receipt.kaspi.kz/..."/></div><button className="secondary wide" disabled={receiptBusy || !receiptUrl.trim()} onClick={uploadDocReceipt}><ShieldCheck size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}</button>`;
source = replaceRequired(source, oldDocUpload, newDocUpload, 'document receipt input');

writeFileSync(file, source, 'utf8');

const apiFile = new URL('../src/korganApi.js', import.meta.url);
let api = readFileSync(apiFile, 'utf8');
const oldConsultApi = `async function uploadConsultationReceipt(orderId, file) {
  const body = new FormData();
  body.append('file', file);
  const result = await request(\`/miniapp/consultation/payments/\${encodeURIComponent(orderId)}/receipt\`, { method: 'POST', body });
  paymentAnalyticsOnce('consultation', orderId);
  return result;
}`;
const newConsultApi = `async function uploadConsultationReceipt(orderId, receiptUrl) {
  const result = await request(\`/miniapp/consultation/payments/\${encodeURIComponent(orderId)}/receipt-url\`, {
    method: 'POST',
    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),
  });
  paymentAnalyticsOnce('consultation', orderId);
  return result;
}`;
api = replaceRequired(api, oldConsultApi, newConsultApi, 'consultation receipt-url API');

const oldDocumentApi = `async function uploadDocumentReceipt(orderId, file) {
  const body = new FormData();
  body.append('file', file);
  const result = await request(\`/miniapp/documents/payments/\${encodeURIComponent(orderId)}/receipt\`, { method: 'POST', body });
  paymentAnalyticsOnce('document', orderId);
  return result;
}`;
const newDocumentApi = `async function uploadDocumentReceipt(orderId, receiptUrl) {
  const result = await request(\`/miniapp/documents/payments/\${encodeURIComponent(orderId)}/receipt-url\`, {
    method: 'POST',
    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),
  });
  paymentAnalyticsOnce('document', orderId);
  return result;
}`;
api = replaceRequired(api, oldDocumentApi, newDocumentApi, 'document receipt-url API');
writeFileSync(apiFile, api, 'utf8');

const polishFile = new URL('../src/ux-polish-v2.js', import.meta.url);
let polish = readFileSync(polishFile, 'utf8');
const notificationStart = polish.indexOf('function notificationSettings() {');
const notificationEndMarker = '\n}\n\nfunction apply()';
const notificationEnd = polish.indexOf(notificationEndMarker, notificationStart);
if (notificationStart < 0 || notificationEnd < 0) {
  throw new Error('KORGAN notification settings block not found; refusing to patch build.');
}
const notificationFunction = `function notificationSettings() {
  const profile = document.querySelector('main.page .profile-card');

  // Notification preferences belong to Profile only. Remove any stale section
  // immediately when React navigates to Home, Cases, AI lawyer or any other tab.
  document.querySelectorAll('.korgan-notification-settings').forEach((section) => {
    if (!profile || section.parentElement !== profile.parentElement) section.remove();
  });

  if (!profile || profile.parentElement?.querySelector('.korgan-notification-settings')) return;
  const kk = isKazakh();
  const section = document.createElement('section');
  section.className = 'korgan-notification-settings';
  const kicker = document.createElement('span');
  kicker.className = 'section-kicker';
  kicker.textContent = kk ? 'ХАБАРЛАМАЛАР' : 'УВЕДОМЛЕНИЯ';
  section.append(kicker);
  section.append(settingRow(kk ? 'Хабарлама дыбысы' : 'Звук уведомлений', kk ? 'Маңызды оқиғалар үшін қысқа дыбыс' : 'Короткий звук для важных событий', SOUND_KEY));
  section.append(settingRow(kk ? 'Діріл' : 'Виброотклик', kk ? 'Telegram қолдайтын құрылғыларда' : 'На устройствах, где Telegram это поддерживает', HAPTIC_KEY));
  const info = document.createElement('p');
  info.className = 'korgan-notification-info';
  info.textContent = kk ? 'Қалқымалы хабарламалар бірнеше секундтан кейін автоматты түрде жоғалады.' : 'Всплывающие уведомления автоматически исчезают через несколько секунд.';
  section.append(info);
  profile.insertAdjacentElement('afterend', section);
}`;
polish = polish.slice(0, notificationStart) + notificationFunction + polish.slice(notificationEnd + 2);
writeFileSync(polishFile, polish, 'utf8');
