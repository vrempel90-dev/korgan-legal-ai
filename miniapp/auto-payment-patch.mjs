import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

function replaceExact(file, oldText, newText, label) {
  const full = path.join(root, file);
  let source = fs.readFileSync(full, 'utf8');
  if (source.includes(newText)) return;
  if (!source.includes(oldText)) {
    throw new Error(`AUTO_PAYMENT_PATCH_MISSING ${label} in ${file}`);
  }
  source = source.replace(oldText, newText);
  fs.writeFileSync(full, source, 'utf8');
}

replaceExact(
  'src/korganApi.js',
  "    || (parity?.document_payments_enabled && parity?.document_manual_confirmation !== true)\n",
  "    || (parity?.document_payments_enabled && (parity?.document_manual_confirmation !== false || parity?.document_ai_receipt_verification !== true || parity?.document_auto_generation_after_receipt !== true))\n",
  'runtime-payment-contract',
);

replaceExact(
  'src/main.jsx',
  "    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.',\n    waitingAdmin: 'Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Теперь можно запустить юридический анализ и генерацию Word. Новая оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',\n    paymentRejected: 'Оплата не подтверждена. Загрузите другой полный чек.', manualCheck: 'Ручное подтверждение', manualCheckSub: 'AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.',\n",
  "    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ и загрузите полный чек — KORGAN AI проверит его автоматически.',\n    waitingAdmin: 'Старая платёжная заявка ожидает обработки. Новые оплаты проверяются KORGAN AI автоматически.', paymentApproved: 'Оплата проверена', paymentApprovedText: 'Оплата уже проверена. Повторная оплата не требуется.', checkPayment: 'Обновить статус', startPaidGeneration: 'Повторить подготовку без новой оплаты',\n    paymentRejected: 'Чек не прошёл AI-проверку. Загрузите другой полный чек.', manualCheck: 'AI-проверка оплаты', manualCheckSub: 'KORGAN AI проверяет сумму, успешный статус, дату/время, номер операции и признаки изменения чека. При успешной проверке документ готовится автоматически.',\n",
  'ru-payment-copy',
);

replaceExact(
  'src/main.jsx',
  "    dataControl: 'Данные под контролем', dataControlSub: 'Mini App использует отдельный API и не изменяет production Telegram‑агента.', runtime: 'Юридическое ядро', secure: 'Защищённое хранение', refresh: 'Обновить', support: 'Техподдержка',\n    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.',\n",
  "    dataControl: 'Данные под контролем', dataControlSub: 'Mini App использует отдельный API и не изменяет production Telegram‑агента.', runtime: 'Юридическое ядро', secure: 'Защищённое хранение', refresh: 'Обновить', support: 'Техподдержка',\n    helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация начинается только после успешной автоматической AI‑проверки загруженного чека.',\n",
  'ru-help-copy',
);

replaceExact(
  'src/main.jsx',
  "    documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.', waitingAdmin: 'Чек алдын ала тексеруден өтті. Kaspi Pay тарихы бойынша қолмен растау күтілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Енді құқықтық талдау мен Word генерациясын бастауға болады. Қайта төлем қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Басқа толық чекті жүктеңіз.', manualCheck: 'Қолмен растау', manualCheckSub: 'AI банк төлемін түпкілікті растамайды — әкімші нақты төлемді тексереді.', filingReady: 'Беруге дайын', preliminary: 'Алдын ала құжат', verified: 'Тексерулер өтті', needsCheck: 'Тексеру қажет', quality: 'Сапа', status: 'Мәртебе', check: 'Тексеру', pricing: 'Тарифтер мен лимиттер', freePerDay: 'Күніне тегін кеңес', consultPrice: 'Лимиттен кейінгі кеңес', language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', runtime: 'Заңдық ядро', secure: 'Қорғалған сақтау', refresh: 'Жаңарту', support: 'Техқолдау', helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем мен қолмен растаудан бұрын басталмайды.',\n",
  "    documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз және толық чекті жүктеңіз — KORGAN AI оны автоматты түрде тексереді.', waitingAdmin: 'Ескі төлем өтінімі өңдеуді күтуде. Жаңа төлемдерді KORGAN AI автоматты түрде тексереді.', paymentApproved: 'Төлем тексерілді', paymentApprovedText: 'Төлем тексерілген. Қайта төлеу қажет емес.', checkPayment: 'Мәртебені жаңарту', startPaidGeneration: 'Жаңа төлемсіз қайта дайындау', paymentRejected: 'Чек AI-тексеруден өтпеді. Басқа толық чекті жүктеңіз.', manualCheck: 'AI төлем тексеруі', manualCheckSub: 'KORGAN AI соманы, сәтті төлем мәртебесін, күн/уақытты, операция нөмірін және чек өзгертілу белгілерін тексереді. Тексеру сәтті болса, құжат автоматты түрде дайындалады.', filingReady: 'Беруге дайын', preliminary: 'Алдын ала құжат', verified: 'Тексерулер өтті', needsCheck: 'Тексеру қажет', quality: 'Сапа', status: 'Мәртебе', check: 'Тексеру', pricing: 'Тарифтер мен лимиттер', freePerDay: 'Күніне тегін кеңес', consultPrice: 'Лимиттен кейінгі кеңес', language: 'Тіл', deleteAll: 'Барлық деректерімді жою', dataControl: 'Деректер бақылауда', dataControlSub: 'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', runtime: 'Заңдық ядро', secure: 'Қорғалған сақтау', refresh: 'Жаңарту', support: 'Техқолдау', helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат генерациясы жүктелген чек автоматты AI-тексеруден сәтті өткеннен кейін ғана басталады.',\n",
  'kk-payment-copy',
);

replaceExact(
  'src/main.jsx',
  "    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin); }\n    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }\n",
  "    try {\n      const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file);\n      if (result?.document_base64) {\n        setDocumentResult(result); setDocPayment(null);\n        setActiveCase(prev => ({ ...prev, status: result.status, title: result.title, verification_status: result.verification_status, has_document: true, filing_ready: result.filing_ready, release_status: result.release_status, quality_score: result.quality_score }));\n        await refreshCases(); setScreen('ready'); return;\n      }\n      setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin);\n    }\n    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }\n",
  'receipt-auto-ready',
);

replaceExact(
  'src/main.jsx',
  "{pricing?.document_payments_enabled && <div className=\"fact\"><span>{t.manualCheck}</span><strong>{runtimeInfo?.parity?.document_manual_confirmation ? 'ON' : 'OFF'}</strong></div>}",
  "{pricing?.document_payments_enabled && <div className=\"fact\"><span>{t.manualCheck}</span><strong>{runtimeInfo?.parity?.document_ai_receipt_verification ? 'ON' : 'OFF'}</strong></div>}",
  'profile-ai-verification-status',
);

console.log('AUTO_PAYMENT_UI_PATCH_OK');
