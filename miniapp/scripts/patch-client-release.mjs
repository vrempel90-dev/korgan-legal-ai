import { readFileSync, writeFileSync } from 'node:fs';

function replaceRequired(text, from, to, label) {
  const index = text.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to patch build.`);
  return text.slice(0, index) + to + text.slice(index + from.length);
}

const mainFile = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(mainFile, 'utf8');

// Client surface: the AI agent remains an internal runtime, never a separate
// customer-facing persona or navigation concept.
source = replaceRequired(
  source,
  "home: 'Главная', cases: 'Дела', lawyer: 'AI-юрист', profile: 'Профиль', help: 'Помощь',",
  "home: 'Главная', cases: 'Дела', lawyer: 'Консультация', profile: 'Профиль', help: 'Помощь',",
  'RU client consultation label',
);
source = replaceRequired(
  source,
  "home: 'Басты', cases: 'Істер', lawyer: 'AI-заңгер', profile: 'Профиль', help: 'Көмек',",
  "home: 'Басты', cases: 'Істер', lawyer: 'Кеңес', profile: 'Профиль', help: 'Көмек',",
  'KK client consultation label',
);
source = source
  .replaceAll("heroTitle: 'Профессиональный AI-юрист'", "heroTitle: 'Юридическая помощь KORGAN'")
  .replaceAll("heroText: 'Консультации, анализ материалов, документы и контроль качества в одном рабочем пространстве.'", "heroText: 'Консультации, анализ материалов и подготовка документов в одном рабочем пространстве.'")
  .replaceAll("heroTitle: 'Кәсіби AI-заңгер'", "heroTitle: 'KORGAN заң көмегі'")
  .replaceAll("heroText: 'Кеңес, материалдарды талдау, құжаттар және сапаны бақылау бір жұмыс кеңістігінде.'", "heroText: 'Кеңес, материалдарды талдау және құжаттарды дайындау бір жұмыс кеңістігінде.'")
  .replaceAll("dataControlSub: 'Mini App использует отдельный API и не изменяет production Telegram‑агента.'", "dataControlSub: 'Дела, материалы и готовые документы доступны только в вашем профиле KORGAN.'")
  .replaceAll("dataControlSub: 'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.'", "dataControlSub: 'Істер, материалдар және дайын құжаттар тек KORGAN профиліңізде қолжетімді.'")
  .replaceAll("helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.'", "helpText: 'Создайте дело, добавьте факты и материалы, получите консультацию и подготовьте документ. После подтверждения оплаты KORGAN автоматически запускает подготовку документа и сохраняет результат в «Мои дела».'")
  .replaceAll("helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем мен қолмен растаудан бұрын басталмайды.'", "helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, кеңес алыңыз және құжат дайындаңыз. Төлем расталғаннан кейін KORGAN құжатты автоматты түрде дайындап, «Менің істерім» бөліміне сақтайды.'")
  .replaceAll("admin: 'Проверка оплат'", "admin: 'Админ-центр'")
  .replaceAll("adminTitle: 'Оплаты документов'", "adminTitle: 'Админ-центр KORGAN'")
  .replaceAll("adminEmpty: 'Чеков на ручную проверку нет'", "adminEmpty: 'Платежей пока нет'")
  .replaceAll("anomalies: 'Аномалии AI'", "anomalies: 'Проверка чека'")
  .replaceAll("admin: 'Төлемдерді тексеру'", "admin: 'Әкімші орталығы'")
  .replaceAll("adminTitle: 'Құжат төлемдері'", "adminTitle: 'KORGAN әкімші орталығы'")
  .replaceAll("adminEmpty: 'Қолмен тексерілетін чек жоқ'", "adminEmpty: 'Әзірге төлем жоқ'")
  .replaceAll("anomalies: 'AI аномалиялары'", "anomalies: 'Чекті тексеру'")
  .replaceAll("'Ваш юридический AI-помощник'", "'Юридическая консультация'")
  .replaceAll("'Сіздің заңгерлік AI-көмекшіңіз'", "'Заң консультациясы'");

// The system/runtime card is internal. Ordinary customers must not see service
// names, encryption implementation details or runtime flags.
source = replaceRequired(
  source,
  '<section className="analysis-card system-card">',
  '{pricing?.is_admin && <section className="analysis-card system-card">',
  'profile internal system card start',
);
source = replaceRequired(
  source,
  '</section><section className="privacy-card static"><LockKeyhole size={20}/>',
  '</section>}<section className="privacy-card static"><LockKeyhole size={20}/>',
  'profile internal system card end',
);

// Admin center lives in MiniApp and shows the complete payment lifecycle.
source = replaceRequired(
  source,
  "try { const result = await korganApi.adminDocumentPayments('awaiting_admin'); setAdminOrders(result.orders || []); }",
  "try { const result = await korganApi.adminDocumentPayments('all'); setAdminOrders(result.orders || []); }",
  'admin all payment statuses',
);
source = replaceRequired(
  source,
  '<div className="fact"><span>{t.clientRef}</span><strong>{order.client_ref}</strong></div>',
  '<div className="fact"><span>{t.status}</span><strong>{order.status}</strong></div><div className="fact"><span>{t.clientRef}</span><strong>{order.client_ref}</strong></div>',
  'admin order status row',
);
source = replaceRequired(
  source,
  '<div className="admin-actions"><button className="secondary danger" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, false)}><XCircle size={17}/>{t.reject}</button><button className="primary" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, true)}><CheckCircle2 size={17}/>{t.approve}</button></div>',
  '{order.status === \'awaiting_admin\' && <div className="admin-actions"><button className="secondary danger" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, false)}><XCircle size={17}/>{t.reject}</button><button className="primary" disabled={adminBusy} onClick={() => decideAdminOrder(order.order_id, true)}><CheckCircle2 size={17}/>{t.approve}</button></div>}',
  'admin emergency decision actions',
);

writeFileSync(mainFile, source, 'utf8');

const apiFile = new URL('../src/korganApi.js', import.meta.url);
let apiSource = readFileSync(apiFile, 'utf8');

// The live payment verifier is automatic. patch-home historically rewrites this
// flag to manual=true; restore the actual API contract after that patch runs.
apiSource = replaceRequired(
  apiSource,
  "(parity?.document_payments_enabled && parity?.document_manual_confirmation !== true)",
  "(parity?.document_payments_enabled && parity?.document_manual_confirmation !== false)",
  'automatic payment parity requirement',
);
apiSource = replaceRequired(
  apiSource,
  "adminDocumentPayments: (status = 'awaiting_admin') => request(`/miniapp/admin/document-payments?status=${encodeURIComponent(status)}`),",
  `adminDocumentPayments: async (status = 'all') => {
    if (status !== 'all') return request(\`/miniapp/admin/document-payments?status=\${encodeURIComponent(status)}\`);
    const statuses = ['pending_receipt', 'awaiting_admin', 'approved', 'consumed', 'cancelled'];
    const results = await Promise.all(statuses.map(value => request(\`/miniapp/admin/document-payments?status=\${encodeURIComponent(value)}\`)));
    const orders = results.flatMap(result => result?.orders || []);
    orders.sort((a, b) => Number(b?.order_id || 0) - Number(a?.order_id || 0));
    return { orders };
  },`,
  'admin all statuses API',
);
writeFileSync(apiFile, apiSource, 'utf8');
