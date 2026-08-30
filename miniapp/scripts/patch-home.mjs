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

// Production payment UX: file upload stays active. Backend is the only payment
// authority and verifies the fiscal QR through Kaspi OFD before generation.
source = replaceRequired(
  source,
  "paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите одну консультацию через Kaspi и загрузите полный чек. После автоматической проверки ответ продолжится по этому же вопросу.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек', checkingReceipt: 'Проверяю чек…'",
  "paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите через Kaspi, затем нажмите «Я оплатил» и выберите электронный чек. Проверка проходит автоматически.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Я оплатил', checkingReceipt: 'Проверяем оплату…'",
  'Russian payment copy',
);
source = replaceRequired(
  source,
  "documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.'",
  "documentPayment: 'Оплата документа', documentPaymentText: 'Оплатите через Kaspi. После оплаты нажмите «Я оплатил» и выберите электронный чек PDF или фото. KORGAN проверит сумму, БИН, РНМ, дату, время и уникальность чека через Kaspi ОФД и сразу начнёт готовить выбранный документ.'",
  'Russian document payment copy',
);
source = replaceRequired(
  source,
  "paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Kaspi арқылы бір кеңес ақысын төлеп, толық чекті жүктеңіз. Автоматты тексеруден кейін осы сұрақ бойынша жауап жалғасады.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу', checkingReceipt: 'Чек тексерілуде…'",
  "paymentNeeded: 'Тегін лимит аяқталды', consultPaymentText: 'Kaspi арқылы төлеңіз, содан кейін «Мен төледім» батырмасын басып, электрондық чекті таңдаңыз. Тексеру автоматты түрде өтеді.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Мен төледім', checkingReceipt: 'Төлем тексерілуде…'",
  'Kazakh payment copy',
);
source = replaceRequired(
  source,
  "documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.'",
  "documentPayment: 'Құжат төлемі', documentPaymentText: 'Kaspi арқылы төлеңіз. Төлемнен кейін «Мен төледім» батырмасын басып, PDF немесе фото түріндегі электрондық чекті таңдаңыз. KORGAN соманы, БСН/ЖСН-ды, РНМ-ды, күн мен уақытты және чектің бірегейлігін Kaspi ОФД арқылы тексеріп, таңдалған құжатты бірден дайындайды.'",
  'Kazakh document payment copy',
);

const oldUploadDocReceipt = `  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin); }
    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }
  };`;
const newUploadDocReceipt = `  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try {
      const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file);
      if (result?.document_base64) {
        setDocumentResult(result); setDocPayment(null);
        setActiveCase(prev => ({ ...prev, status: result.status, title: result.title, verification_status: result.verification_status, has_document: true, filing_ready: result.filing_ready, release_status: result.release_status, quality_score: result.quality_score }));
        await refreshCases(); setScreen('ready'); return;
      }
      if (result?.payment) {
        setDocPayment(result.payment); setNotice(result.message || t.paymentApproved); return;
      }
      throw new Error(language === 'kk' ? 'Төлем расталды, бірақ құжат күйін қалпына келтіру мүмкін болмады.' : 'Оплата подтверждена, но не удалось восстановить состояние документа. Повторно платить не нужно.');
    } catch (error) {
      if (error?.status === 503 && docPayment?.order_id) {
        try {
          const status = await korganApi.documentPaymentStatus(docPayment.order_id);
          if (status?.payment) setDocPayment(status.payment);
        } catch {}
      }
      setNotice(error?.message || t.down);
    } finally { setReceiptBusy(false); }
  };`;
source = replaceRequired(source, oldUploadDocReceipt, newUploadDocReceipt, 'document receipt success flow');

source = replaceRequired(
  source,
  "{pricing?.document_payments_enabled && <div className=\"price-note\"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · {t.manualCheck}</span></div>}",
  "{pricing?.document_payments_enabled && <div className=\"price-note\"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · Kaspi ОФД</span></div>}",
  'document price payment mode',
);

const paymentStartMarker = "  if (screen === 'doc-payment' && docPayment) {";
const paymentEndMarker = "\n\n  if (screen === 'ready')";
const paymentStart = source.indexOf(paymentStartMarker);
const paymentEnd = source.indexOf(paymentEndMarker, paymentStart);
if (paymentStart < 0 || paymentEnd < 0) {
  throw new Error('KORGAN document payment screen not found; refusing to patch build.');
}
const paymentScreen = `  if (screen === 'doc-payment' && docPayment) {
    const approved = docPayment.status === 'approved';
    const openKaspi = () => {
      const tg = window.Telegram?.WebApp;
      if (tg?.openLink) tg.openLink(docPayment.kaspi_url);
      else window.open(docPayment.kaspi_url, '_blank', 'noopener,noreferrer');
    };
    return <div className="app-shell"><Header title={t.documentPayment} back="case"/><main className="page payment-page"><div className={\`payment-stage-icon \${approved ? 'approved' : ''}\`}>{approved ? <CheckCircle2 size={38}/> : <Banknote size={38}/>}</div><span className="section-kicker">KORGAN PAYMENT · #{docPayment.order_id}</span><h1>{approved ? t.paymentApproved : t.documentPayment}</h1><p>{approved ? (language === 'kk' ? 'Төлем расталды. Қайта төлеудің қажеті жоқ. Құжатты дайындауды қайталауға болады.' : 'Оплата подтверждена. Повторно платить не нужно. Если генерация прервалась, повторите только подготовку документа.') : t.documentPaymentText}</p><div className="payment-amount centered">{money(docPayment.amount_kzt)}</div>{notice && <div className="warning-note"><AlertTriangle size={17}/>{notice}</div>}{!approved && <><button className="primary wide" onClick={openKaspi}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><label className="secondary wide receipt-upload"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" disabled={receiptBusy} onChange={uploadDocReceipt}/></label><small>{language === 'kk' ? 'PDF/JPG/PNG/WEBP. KORGAN фискалдық QR-ды өзі оқиды.' : 'PDF/JPG/PNG/WEBP. KORGAN сам прочитает фискальный QR из чека.'}</small></>}{approved && <button className="primary wide" disabled={busy} onClick={generateDocument}>{busy ? <LoaderCircle className="spin" size={18}/> : <RefreshCw size={18}/>} {busy ? t.generating : (language === 'kk' ? 'Құжатты төлемсіз қайта дайындау' : 'Повторить генерацию без оплаты')}</button>}</main></div>;
  }`;
source = source.slice(0, paymentStart) + paymentScreen + source.slice(paymentEnd);

writeFileSync(file, source, 'utf8');
