import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

function replaceOnce(source, from, to, label) {
  if (!source.includes(from)) {
    throw new Error(`patch-production-runtime: missing ${label}`);
  }
  return source.replace(from, to);
}

function patchFile(relative, transform) {
  const file = path.join(root, relative);
  const before = fs.readFileSync(file, 'utf8');
  const after = transform(before);
  if (after !== before) fs.writeFileSync(file, after, 'utf8');
}

patchFile('src/korganApi.js', source => {
  source = replaceOnce(
    source,
    "  const tg = window.Telegram?.WebApp;\n  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;",
    "  const tg = window.Telegram?.WebApp;\n  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;",
    'korganApi request prelude',
  );
  source = replaceOnce(
    source,
    "  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;",
    "  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;",
    'korganApi Telegram auth',
  );
  source = replaceOnce(
    source,
    "  uploadConsultationReceipt,\n  retryPaidConsultation:",
    "  uploadConsultationReceipt,\n  verifyConsultationReceiptUrl: (orderId, receiptUrl) => request(`/miniapp/consultation/payments/${encodeURIComponent(orderId)}/receipt-url`, {\n    method: 'POST',\n    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),\n  }),\n  retryPaidConsultation:",
    'consultation OFD API',
  );
  source = replaceOnce(
    source,
    "  uploadDocumentReceipt,\n  documentPaymentStatus:",
    "  uploadDocumentReceipt,\n  verifyDocumentReceiptUrl: (orderId, receiptUrl) => request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/receipt-url`, {\n    method: 'POST',\n    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),\n  }),\n  documentPaymentStatus:",
    'document OFD API',
  );
  return source;
});

patchFile('src/main.jsx', source => {
  source = replaceOnce(
    source,
    "  const [receiptBusy, setReceiptBusy] = useState(false);\n  const [documentResult, setDocumentResult] = useState(null);",
    "  const [receiptBusy, setReceiptBusy] = useState(false);\n  const [receiptUrl, setReceiptUrl] = useState('');\n  const [documentResult, setDocumentResult] = useState(null);",
    'receipt URL state',
  );

  source = replaceOnce(
    source,
    "    paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите одну консультацию через Kaspi и загрузите полный чек. После автоматической проверки ответ продолжится по этому же вопросу.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Загрузить чек', checkingReceipt: 'Проверяю чек…', retryPaid: 'Повторить ответ без новой оплаты', paidSaved: 'Оплата сохранена. Повторно платить не нужно.',",
    "    paymentNeeded: 'Бесплатный лимит исчерпан', consultPaymentText: 'Оплатите консультацию через Kaspi. Затем отсканируйте QR фискального чека и вставьте ссылку receipt.kaspi.kz. KORGAN проверит оплату по Kaspi ОФД без AI.', payKaspi: 'Оплатить через Kaspi', uploadReceipt: 'Проверить QR-чек', checkingReceipt: 'Проверяю Kaspi ОФД…', retryPaid: 'Повторить ответ без новой оплаты', paidSaved: 'Оплата сохранена. Повторно платить не нужно.',",
    'RU consultation payment copy',
  );
  source = replaceOnce(
    source,
    "    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.',\n    waitingAdmin: 'Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Теперь можно запустить юридический анализ и генерацию Word. Новая оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',\n    paymentRejected: 'Оплата не подтверждена. Загрузите другой полный чек.', manualCheck: 'Ручное подтверждение', manualCheckSub: 'AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.',",
    "    documentPayment: 'Оплата документа', documentPaymentText: 'AI ещё не формировал документ. Оплатите через Kaspi, затем отсканируйте QR фискального чека и вставьте ссылку receipt.kaspi.kz. После проверки Kaspi ОФД подготовка Word начнётся автоматически.',\n    waitingAdmin: 'Фискальный чек проверяется через Kaspi ОФД.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Kaspi ОФД подтвердил оплату. Повторная оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',\n    paymentRejected: 'Оплата не подтверждена. Проверьте QR-ссылку фискального чека.', manualCheck: 'Проверка Kaspi ОФД', manualCheckSub: 'KORGAN проверяет фискальную QR-ссылку receipt.kaspi.kz, сумму, получателя, дату и уникальность чека. AI не принимает решение об оплате.',",
    'RU document payment copy',
  );
  source = replaceOnce(
    source,
    "    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.',",
    "    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. При оплате KORGAN проверяет QR фискального чека через Kaspi ОФД до начала генерации.',",
    'RU help payment copy',
  );

  source = replaceOnce(
    source,
    "consultPaymentText: 'Kaspi арқылы бір кеңес ақысын төлеп, толық чекті жүктеңіз. Автоматты тексеруден кейін осы сұрақ бойынша жауап жалғасады.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'Чекті жүктеу', checkingReceipt: 'Чек тексерілуде…'",
    "consultPaymentText: 'Kaspi арқылы кеңес ақысын төлеңіз. Содан кейін фискалдық чектегі QR-кодты сканерлеп, receipt.kaspi.kz сілтемесін енгізіңіз. KORGAN төлемді Kaspi ОФД арқылы AI-сыз тексереді.', payKaspi: 'Kaspi арқылы төлеу', uploadReceipt: 'QR-чекті тексеру', checkingReceipt: 'Kaspi ОФД тексерілуде…'",
    'KK consultation payment copy',
  );
  source = replaceOnce(
    source,
    "documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.', waitingAdmin: 'Чек алдын ала тексеруден өтті. Kaspi Pay тарихы бойынша қолмен растау күтілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Енді құқықтық талдау мен Word генерациясын бастауға болады. Қайта төлем қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Басқа толық чекті жүктеңіз.', manualCheck: 'Қолмен растау', manualCheckSub: 'AI банк төлемін түпкілікті растамайды — әкімші нақты төлемді тексереді.'",
    "documentPaymentText: 'AI құжатты әлі дайындаған жоқ. Kaspi арқылы төлеңіз, фискалдық чектегі QR-кодты сканерлеп, receipt.kaspi.kz сілтемесін енгізіңіз. Kaspi ОФД тексергеннен кейін Word автоматты түрде дайындала бастайды.', waitingAdmin: 'Фискалдық чек Kaspi ОФД арқылы тексерілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Kaspi ОФД төлемді растады. Қайта төлеу қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Фискалдық чектің QR-сілтемесін тексеріңіз.', manualCheck: 'Kaspi ОФД тексеруі', manualCheckSub: 'KORGAN receipt.kaspi.kz фискалдық QR-сілтемесін, соманы, алушыны, күнді және чектің бірегейлігін тексереді. AI төлем туралы шешім қабылдамайды.'",
    'KK document payment copy',
  );

  source = replaceOnce(
    source,
    "  const uploadConsultReceipt = async event => {\n    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !consultPayment || receiptBusy) return;\n    setReceiptBusy(true); setNotice('');\n    try { const result = await korganApi.uploadConsultationReceipt(consultPayment.order_id, file); appendAnswer(result); setConsultPayment(null); }\n    catch (error) { if (error?.status === 503) { setConsultPayment(prev => ({ ...prev, paidPending: true })); setNotice(t.paidSaved); } else setNotice(error?.message || t.down); }\n    finally { setReceiptBusy(false); }\n  };",
    "  const verifyConsultReceipt = async () => {\n    const url = receiptUrl.trim(); if (!url || !consultPayment || receiptBusy) return;\n    setReceiptBusy(true); setNotice('');\n    try {\n      const result = await korganApi.verifyConsultationReceiptUrl(consultPayment.order_id, url);\n      appendAnswer(result); setConsultPayment(null); setReceiptUrl('');\n      setNotice(language === 'kk' ? 'Kaspi ОФД төлемді растады.' : 'Kaspi ОФД подтвердил оплату.');\n    } catch (error) { setNotice(error?.message || t.down); }\n    finally { setReceiptBusy(false); }\n  };",
    'consultation OFD handler',
  );

  source = replaceOnce(
    source,
    "  const uploadDocReceipt = async event => {\n    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;\n    setReceiptBusy(true); setNotice('');\n    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin); }\n    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }\n  };",
    "  const verifyDocReceipt = async () => {\n    const url = receiptUrl.trim(); if (!url || !docPayment || receiptBusy) return;\n    setReceiptBusy(true); setNotice('');\n    try {\n      const result = await korganApi.verifyDocumentReceiptUrl(docPayment.order_id, url);\n      setDocPayment(result.payment); setReceiptUrl(''); setNotice(result.message || t.paymentApproved);\n      if (result?.payment?.status === 'approved') window.setTimeout(() => generateDocument(), 0);\n    } catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }\n  };",
    'document OFD handler',
  );

  source = replaceOnce(
    source,
    "  const BottomNav = () => <nav className=\"bottom-nav\">\n    <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>\n    <button className={screen === 'cases' ? 'active' : ''} onClick={async () => { try { await refreshCases(); } catch {} go('cases'); }}><FolderOpen size={20}/><span>{t.cases}</span></button>\n    <button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>\n    <button className={screen === 'help' ? 'active' : ''} onClick={() => go('help')}><CircleHelp size={20}/><span>{t.help}</span></button>\n    <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>\n  </nav>;",
    "  const BottomNav = () => <nav className=\"bottom-nav\">\n    <button className={screen === 'home' ? 'active' : ''} onClick={() => go('home')}><Home size={20}/><span>{t.home}</span></button>\n    <button className={screen === 'profile' ? 'active' : ''} onClick={() => go('profile')}><UserRound size={20}/><span>{t.profile}</span></button>\n  </nav>;",
    'two-button bottom nav',
  );

  source = replaceOnce(
    source,
    "<label className=\"secondary wide receipt-upload\"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type=\"file\" accept=\".pdf,.jpg,.jpeg,.png,.webp\" disabled={receiptBusy} onChange={uploadConsultReceipt}/></label>",
    "<div className=\"receipt-url-box\"><input value={receiptUrl} onChange={e => setReceiptUrl(e.target.value)} placeholder={language === 'kk' ? 'receipt.kaspi.kz сілтемесін енгізіңіз' : 'Вставьте ссылку receipt.kaspi.kz'} inputMode=\"url\" autoCapitalize=\"none\" autoCorrect=\"off\"/><button className=\"secondary wide\" disabled={receiptBusy || !receiptUrl.trim()} onClick={verifyConsultReceipt}>{receiptBusy ? <LoaderCircle className=\"spin\" size={18}/> : <ShieldCheck size={18}/>} {language === 'kk' ? 'QR-чекті тексеру' : 'Проверить QR-чек'}</button></div>",
    'consultation receipt URL UI',
  );

  source = replaceOnce(
    source,
    "<label className=\"secondary wide receipt-upload\"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type=\"file\" accept=\".pdf,.jpg,.jpeg,.png,.webp\" disabled={receiptBusy} onChange={uploadDocReceipt}/></label>",
    "<div className=\"receipt-url-box\"><input value={receiptUrl} onChange={e => setReceiptUrl(e.target.value)} placeholder={language === 'kk' ? 'receipt.kaspi.kz сілтемесін енгізіңіз' : 'Вставьте ссылку receipt.kaspi.kz'} inputMode=\"url\" autoCapitalize=\"none\" autoCorrect=\"off\"/><button className=\"secondary wide\" disabled={receiptBusy || !receiptUrl.trim()} onClick={verifyDocReceipt}>{receiptBusy ? <LoaderCircle className=\"spin\" size={18}/> : <ShieldCheck size={18}/>} {language === 'kk' ? 'QR-чекті тексеру' : 'Проверить QR-чек'}</button></div>",
    'document receipt URL UI',
  );

  source = source.replace(
    "if (result.payment_required && result.payment) { setFreeRemaining(0); setConsultPayment({ ...result.payment, paidPending: false }); }",
    "if (result.payment_required && result.payment) { setFreeRemaining(0); setReceiptUrl(''); setConsultPayment({ ...result.payment, paidPending: false }); }",
  );
  source = source.replace(
    "if (result?.payment_required && result?.payment) { setDocPayment(result.payment); setScreen('doc-payment'); return; }",
    "if (result?.payment_required && result?.payment) { setReceiptUrl(''); setDocPayment(result.payment); setScreen('doc-payment'); return; }",
  );

  return source;
});

patchFile('public/client-safe-ui.js', source => replaceOnce(
  source,
  "        const visible = index === 0 || index === 4;",
  "        const visible = buttons.length <= 2 || index === 0 || index === buttons.length - 1;",
  'two-button dock compatibility',
));

console.log('KORGAN production runtime patches applied');
