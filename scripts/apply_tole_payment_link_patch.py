from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_main() -> None:
    path = Path("miniapp/src/main.jsx")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "import { requireDocumentPayment, startDocumentPaymentPolling } from './documentPaymentPolling';",
        "import { isAutomaticDocumentPayment, requireDocumentPayment, shouldPollDocumentPayment, startDocumentPaymentPolling } from './documentPaymentPolling';",
        "payment polling import",
    )
    text = replace_once(
        text,
        "    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.',\n    waitingAdmin: 'Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Теперь можно запустить юридический анализ и генерацию Word. Новая оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',\n    paymentRejected: 'Оплата не подтверждена. Загрузите другой полный чек.', manualCheck: 'Ручное подтверждение', manualCheckSub: 'AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.',",
        "    documentPayment: 'Оплата документа', documentPaymentText: 'Юридический анализ и генерация Word ещё не начались. Оплатите документ и дождитесь подтверждения платежа.',\n    automaticPayment: 'Автоматическая оплата', automaticPaymentText: 'Нажмите «Оплатить через Kaspi». После оплаты Tole автоматически подтвердит платёж — чек загружать не нужно. Вернитесь в KORGAN и дождитесь запуска документа.', automaticPaymentSecurity: 'Банковский факт подтверждает Tole. KORGAN дополнительно сверяет на сервере статус, валюту KZT и точную сумму заказа.',\n    waitingAdmin: 'Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', paymentApproved: 'Оплата подтверждена', paymentApprovedText: 'Оплата подтверждена. KORGAN автоматически запускает юридический анализ и генерацию Word. Новая оплата не требуется.', checkPayment: 'Проверить подтверждение', startPaidGeneration: 'Подготовить оплаченный документ',\n    paymentRejected: 'Оплата не подтверждена. Загрузите другой полный чек.', manualCheck: 'Ручное подтверждение', manualCheckSub: 'AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.',",
        "ru payment copy",
    )
    text = replace_once(
        text,
        "helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.',",
        "helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до подтверждения оплаты.',",
        "ru help copy",
    )
    text = replace_once(
        text,
        "documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.', waitingAdmin: 'Чек алдын ала тексеруден өтті. Kaspi Pay тарихы бойынша қолмен растау күтілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Енді құқықтық талдау мен Word генерациясын бастауға болады. Қайта төлем қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Басқа толық чекті жүктеңіз.', manualCheck: 'Қолмен растау', manualCheckSub: 'AI банк төлемін түпкілікті растамайды — әкімші нақты төлемді тексереді.',",
        "documentPayment: 'Құжат төлемі', documentPaymentText: 'Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз және төлем расталғанша күтіңіз.', automaticPayment: 'Автоматты төлем', automaticPaymentText: '«Kaspi арқылы төлеу» түймесін басыңыз. Төлемнен кейін Tole төлемді автоматты түрде растайды — чек жүктеу қажет емес. KORGAN-ға оралып, құжаттың іске қосылуын күтіңіз.', automaticPaymentSecurity: 'Банк төлемін Tole растайды. KORGAN серверде мәртебені, KZT валютасын және тапсырыстың нақты сомасын қосымша тексереді.', waitingAdmin: 'Чек алдын ала тексеруден өтті. Kaspi Pay тарихы бойынша қолмен растау күтілуде.', paymentApproved: 'Төлем расталды', paymentApprovedText: 'Төлем расталды. KORGAN құқықтық талдау мен Word генерациясын автоматты түрде бастайды. Қайта төлем қажет емес.', checkPayment: 'Растауды тексеру', startPaidGeneration: 'Төленген құжатты дайындау', paymentRejected: 'Төлем расталмады. Басқа толық чекті жүктеңіз.', manualCheck: 'Қолмен растау', manualCheckSub: 'AI банк төлемін түпкілікті растамайды — әкімші нақты төлемді тексереді.',",
        "kk payment copy",
    )
    text = replace_once(
        text,
        "helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем мен қолмен растаудан бұрын басталмайды.',",
        "helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем расталғанға дейін басталмайды.',",
        "kk help copy",
    )
    text = replace_once(
        text,
        "  const latestCases = useRef(createLatestAction());\n  // Показанное сообщение читается из обработчика опроса, который был создан",
        "  const latestCases = useRef(createLatestAction());\n  // Один Tole-заказ автоматически запускает генерацию только один раз после\n  // server-side подтверждения. Если запуск завершится ошибкой, кнопка на экране\n  // approved остаётся как явный безопасный retry без новой оплаты.\n  const autoStartedPayment = useRef('');\n  // Показанное сообщение читается из обработчика опроса, который был создан",
        "auto start ref",
    )
    text = replace_once(
        text,
        "  useEffect(() => {\n    if (view !== 'doc-payment' || docPayment?.status !== 'awaiting_admin' || !docPayment?.order_id) return undefined;\n    return startDocumentPaymentPolling({\n      orderId: docPayment.order_id,\n      fetchStatus: korganApi.documentPaymentStatus,\n      onPayment: payment => { reportPolling(null); setDocPayment(payment); },\n      onError: reportPolling,\n    });\n  }, [view, docPayment?.status, docPayment?.order_id, t.down]);",
        "  useEffect(() => {\n    if (view !== 'doc-payment' || !docPayment?.order_id || !shouldPollDocumentPayment(docPayment)) return undefined;\n    return startDocumentPaymentPolling({\n      orderId: docPayment.order_id,\n      fetchStatus: korganApi.documentPaymentStatus,\n      onPayment: payment => { reportPolling(null); setDocPayment(payment); },\n      onError: reportPolling,\n    });\n  }, [view, docPayment?.status, docPayment?.order_id, docPayment?.payment_provider, docPayment?.automatic_confirmation, t.down]);",
        "payment polling effect",
    )
    text = replace_once(
        text,
        "  const generateDocument = async () => {\n    if (!activeCase || busy) return; setBusy('generate'); setNotice('');\n    try { await applyGenerationState(await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language)); }\n    catch (error) { setNotice(clientMessage(error)); }\n    finally { setBusy(false); }\n  };\n  // Повтор берёт ту же оплаченную задачу, поэтому второй оплаты не возникает.",
        "  const generateDocument = async () => {\n    if (!activeCase || busy) return; setBusy('generate'); setNotice('');\n    try { await applyGenerationState(await korganApi.generateDocument(activeCase.id, activeCase.document_type, activeCase.language || language)); }\n    catch (error) { setNotice(clientMessage(error)); }\n    finally { setBusy(false); }\n  };\n  useEffect(() => {\n    const automatic = isAutomaticDocumentPayment(docPayment);\n    const approvedOrder = automatic && docPayment?.status === 'approved' ? String(docPayment.order_id || '') : '';\n    if (view !== 'doc-payment' || !approvedOrder || autoStartedPayment.current === approvedOrder) return;\n    autoStartedPayment.current = approvedOrder;\n    generateDocument();\n  }, [view, docPayment?.status, docPayment?.order_id, docPayment?.payment_provider, docPayment?.automatic_confirmation]);\n  // Повтор берёт ту же оплаченную задачу, поэтому второй оплаты не возникает.",
        "automatic generation effect",
    )
    text = replace_once(
        text,
        "{pricing?.document_payments_enabled && <div className=\"price-note\"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · {t.manualCheck}</span></div>}",
        "{pricing?.document_payments_enabled && <div className=\"price-note\"><CreditCard size={16}/><span>{t.docPrice}: <strong>{money(pricing.document_price_kzt)}</strong> · {pricing?.document_payment_provider === 'tole' ? t.automaticPayment : t.manualCheck}</span></div>}",
        "documents price note",
    )

    old = """  if (view === 'doc-payment') {
    const awaiting = docPayment.status === 'awaiting_admin'; const approved = docPayment.status === 'approved';
    return <div className=\"app-shell\"><Header go={go} title={t.documentPayment} back=\"case\"/><main className=\"page payment-page\"><div className={`payment-stage-icon ${approved ? 'approved' : awaiting ? 'waiting' : ''}`}>{approved ? <CheckCircle2 size={38}/> : awaiting ? <Clock3 size={38}/> : <Banknote size={38}/>}</div><span className=\"section-kicker\">KORGAN PREPAY · #{docPayment.order_id}</span><h1>{approved ? t.paymentApproved : awaiting ? t.manualCheck : t.documentPayment}</h1><p>{approved ? t.paymentApprovedText : awaiting ? t.waitingAdmin : t.documentPaymentText}</p><div className=\"payment-amount centered\">{money(docPayment.amount_kzt)}</div><section className=\"analysis-card manual-card\"><div className=\"card-head\"><div><span className=\"section-kicker\">SECURITY</span><h2>{t.manualCheck}</h2></div><ClipboardCheck size={22}/></div><p>{t.manualCheckSub}</p></section>{docPayment.decision_note && !approved && !awaiting && <div className=\"warning-note\"><XCircle size={17}/>{t.paymentRejected}</div>}{notice && <div className=\"warning-note\"><AlertTriangle size={17}/>{notice}</div>}{!approved && !awaiting && <><button className=\"primary wide\" onClick={() => window.open(docPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><label className=\"secondary wide receipt-upload\"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type=\"file\" accept=\".pdf,.jpg,.jpeg,.png,.webp\" disabled={receiptBusy} onChange={uploadDocReceipt}/></label></>}{awaiting && <button className=\"secondary wide\" disabled={busy} onClick={refreshDocPayment}><RefreshCw size={18}/>{t.checkPayment}</button>}{approved && <button className=\"primary wide\" disabled={busy} onClick={generateDocument}>{busyAction === 'generate' ? <LoaderCircle className=\"spin\" size={18}/> : <Sparkles size={18}/>} {busyAction === 'generate' ? t.generating : t.startPaidGeneration}</button>}</main>{nav}</div>;
  }
"""
    new = """  if (view === 'doc-payment') {
    const automatic = isAutomaticDocumentPayment(docPayment);
    const awaiting = !automatic && docPayment.status === 'awaiting_admin';
    const approved = docPayment.status === 'approved';
    const automaticPending = automatic && (docPayment.status === 'pending_receipt' || docPayment.status === 'awaiting_admin');
    const paymentUrl = safeUrl(docPayment.payment_url || docPayment.kaspi_url);
    return <div className=\"app-shell\"><Header go={go} title={t.documentPayment} back=\"case\"/><main className=\"page payment-page\"><div className={`payment-stage-icon ${approved ? 'approved' : (awaiting || automaticPending) ? 'waiting' : ''}`}>{approved ? <CheckCircle2 size={38}/> : (awaiting || automaticPending) ? <Clock3 size={38}/> : <Banknote size={38}/>}</div><span className=\"section-kicker\">KORGAN PREPAY · #{docPayment.order_id}</span><h1>{approved ? t.paymentApproved : automatic ? t.automaticPayment : awaiting ? t.manualCheck : t.documentPayment}</h1><p>{approved ? t.paymentApprovedText : automatic ? t.automaticPaymentText : awaiting ? t.waitingAdmin : t.documentPaymentText}</p><div className=\"payment-amount centered\">{money(docPayment.amount_kzt)}</div>{automatic ? <section className=\"analysis-card manual-card\"><div className=\"card-head\"><div><span className=\"section-kicker\">TOLE · SECURITY</span><h2>{t.automaticPayment}</h2></div><ShieldCheck size={22}/></div><p>{t.automaticPaymentSecurity}</p></section> : <section className=\"analysis-card manual-card\"><div className=\"card-head\"><div><span className=\"section-kicker\">SECURITY</span><h2>{t.manualCheck}</h2></div><ClipboardCheck size={22}/></div><p>{t.manualCheckSub}</p></section>}{docPayment.decision_note && !approved && !awaiting && !automaticPending && <div className=\"warning-note\"><XCircle size={17}/>{t.paymentRejected}</div>}{notice && <div className=\"warning-note\"><AlertTriangle size={17}/>{notice}</div>}{automaticPending && paymentUrl && <button className=\"primary wide\" onClick={() => window.open(paymentUrl, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button>}{!automatic && !approved && !awaiting && <><button className=\"primary wide\" onClick={() => window.open(docPayment.kaspi_url, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><label className=\"secondary wide receipt-upload\"><Paperclip size={18}/>{receiptBusy ? t.checkingReceipt : t.uploadReceipt}<input type=\"file\" accept=\".pdf,.jpg,.jpeg,.png,.webp\" disabled={receiptBusy} onChange={uploadDocReceipt}/></label></>}{awaiting && <button className=\"secondary wide\" disabled={busy} onClick={refreshDocPayment}><RefreshCw size={18}/>{t.checkPayment}</button>}{approved && <button className=\"primary wide\" disabled={busy} onClick={generateDocument}>{busyAction === 'generate' ? <LoaderCircle className=\"spin\" size={18}/> : <Sparkles size={18}/>} {busyAction === 'generate' ? t.generating : t.startPaidGeneration}</button>}</main>{nav}</div>;
  }
"""
    text = replace_once(text, old, new, "document payment screen")
    text = replace_once(
        text,
        "{pricing?.is_admin && <button className=\"primary wide admin-entry\" onClick={openAdmin}><ClipboardCheck size={18}/>{t.admin}</button>}",
        "{pricing?.is_admin && pricing?.document_payment_provider !== 'tole' && <button className=\"primary wide admin-entry\" onClick={openAdmin}><ClipboardCheck size={18}/>{t.admin}</button>}",
        "admin entry",
    )
    text = replace_once(
        text,
        "{pricing?.document_payments_enabled && <div className=\"fact\"><span>{t.manualCheck}</span><strong>{runtimeInfo?.parity?.document_manual_confirmation ? 'ON' : 'OFF'}</strong></div>}",
        "{pricing?.document_payments_enabled && <div className=\"fact\"><span>{pricing?.document_payment_provider === 'tole' ? t.automaticPayment : t.manualCheck}</span><strong>{pricing?.document_payment_provider === 'tole' ? (runtimeInfo?.parity?.automatic_payment_confirmation ? 'ON' : 'OFF') : (runtimeInfo?.parity?.document_manual_confirmation ? 'ON' : 'OFF')}</strong></div>}",
        "profile payment fact",
    )
    path.write_text(text, encoding="utf-8")


def patch_backend() -> None:
    path = Path("korgan/miniapp_tole_payments.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from korgan import miniapp_api_v5 as v5\nfrom korgan import miniapp_document_payments as document_store",
        "from korgan import miniapp_api_v5 as v5\nfrom korgan import miniapp_generation_api as generation_runtime\nfrom korgan import miniapp_document_payments as document_store",
        "generation runtime import",
    )
    text = replace_once(
        text,
        "        if not settings.payments_enabled:\n            return await v5.generate_document(payload, x_telegram_init_data)",
        "        if not settings.payments_enabled:\n            return await generation_runtime.generate_document_job(payload, x_telegram_init_data=x_telegram_init_data)",
        "free generation delegate",
    )
    text = replace_once(
        text,
        "        if order.status == \"approved\":\n            return await v5._run_approved_document(order, x_telegram_init_data=x_telegram_init_data)",
        "        if order.status == \"approved\":\n            # Tole owns payment confirmation only. Durable generation remains\n            # the single executor of paid legal work.\n            return await generation_runtime.generate_document_job(\n                payload, x_telegram_init_data=x_telegram_init_data\n            )",
        "approved generation delegate",
    )
    text = replace_once(
        text,
        'detail="Tole создаёт QR оплаты. Повторите через несколько секунд; новая заявка не создастся."',
        'detail="Tole создаёт ссылку оплаты. Повторите через несколько секунд; новая заявка не создастся."',
        "client payment-link copy",
    )
    text = replace_once(
        text,
        'LOGGER.info("TOLE_PAYMENT_RUNTIME_INSTALLED provider=tole mode=dynamic_qr")',
        'LOGGER.info("TOLE_PAYMENT_RUNTIME_INSTALLED provider=tole mode=payment_link")',
        "runtime mode log",
    )
    path.write_text(text, encoding="utf-8")


def write_ui_test() -> None:
    Path("miniapp/test/tole-payment-ui.test.js").write_text(
        """import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const main = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('Tole document payment exposes a link and hides receipt controls', () => {
  assert.match(main, /const automatic = isAutomaticDocumentPayment\\(docPayment\\)/);
  assert.match(main, /const paymentUrl = safeUrl\\(docPayment\\.payment_url \\|\\| docPayment\\.kaspi_url\\)/);
  assert.match(main, /automaticPending && paymentUrl/);
  assert.match(main, /!automatic && !approved && !awaiting/);
});

test('Tole payment screen says confirmation is automatic', () => {
  assert.match(main, /Tole автоматически подтвердит платёж/);
  assert.match(main, /чек загружать не нужно/);
  assert.match(main, /automaticPaymentSecurity/);
});

test('approved Tole payment auto-starts the existing generation path once', () => {
  assert.match(main, /autoStartedPayment = useRef\\(''\\)/);
  assert.match(main, /docPayment\\?\\.status === 'approved'/);
  assert.match(main, /autoStartedPayment\\.current = approvedOrder;\\s*generateDocument\\(\\)/);
});

test('deferred global generation progress UI remains present and untouched', () => {
  assert.match(main, /if \\(view === 'generating'\\)/);
  assert.match(main, /role=\"progressbar\"/);
});
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    patch_main()
    patch_backend()
    write_ui_test()
