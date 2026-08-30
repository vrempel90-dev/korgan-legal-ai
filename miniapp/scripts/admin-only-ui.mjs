import { readFileSync, writeFileSync } from 'node:fs';

const mainFile = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(mainFile, 'utf8');

function replaceRequired(from, to, label) {
  const index = source.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to build.`);
  source = source.slice(0, index) + to + source.slice(index + from.length);
}

function removeBetween(startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  if (start < 0 || end < 0) throw new Error(`KORGAN ${label} not found; refusing to build.`);
  source = source.slice(0, start) + source.slice(end);
}

// Client-facing AI consultation is disabled. Document generation remains active.
replaceRequired(
  `<button className="action-card home-ai-card" onClick={() => go('chat')}><div className="action-icon consult"><MessageCircle/></div><div className="action-copy"><h2>{t.lawyer}</h2><p>{language === 'kk' ? 'Құқықтық талдау және іс бойынша жауаптар' : 'Правовой анализ и ответы по делу'}</p></div><span className="home-card-arrow"><ChevronRight size={16}/></span></button>`,
  '',
  'home AI card',
);

replaceRequired(
  `<button className={screen === 'chat' ? 'active' : ''} onClick={() => go('chat')}><MessageCircle size={20}/><span>{t.lawyer}</span></button>`,
  '',
  'AI bottom navigation item',
);

// No hidden/deep-link chat screen should survive the production build.
removeBetween(
  `  if (screen === 'chat')`,
  `\n\n  if (screen === 'doc-payment'`,
  'AI chat screen',
);

// Payment decisions are Telegram-admin-only now; MiniApp has no admin queue UI.
removeBetween(
  `  if (screen === 'admin-payments')`,
  `\n\n  if (screen === 'help')`,
  'MiniApp payment admin screen',
);

replaceRequired(
  `{pricing?.is_admin && <button className="primary wide admin-entry" onClick={openAdmin}><ClipboardCheck size={18}/>{t.admin}</button>}`,
  '',
  'MiniApp payment admin entry',
);

// Hide consultation quotas/prices because client AI consultations are disabled.
replaceRequired(
  `<div className="fact"><span>{t.freePerDay}</span><strong>{pricing.consultation_limit_enabled ? pricing.free_consultations_per_day : '∞'}</strong></div>`,
  '',
  'consultation quota profile row',
);
replaceRequired(
  `{pricing.consultation_limit_enabled && <div className="fact"><span>{t.consultPrice}</span><strong>{money(pricing.consultation_price_kzt)}</strong></div>}`,
  '',
  'consultation price profile row',
);

// Customer copy reflects the document-only MiniApp product surface.
source = source
  .replaceAll('Материалы, консультации и готовые документы', 'Материалы и готовые документы')
  .replaceAll('Материалдар, кеңестер және дайын құжаттар', 'Материалдар және дайын құжаттар')
  .replace(
    "helpText: 'Создайте дело, добавьте факты и материалы, задайте вопросы AI‑юристу. Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент. Если включена оплата документов, генерация не начинается до оплаты и ручного подтверждения.'",
    "helpText: 'Создайте дело, добавьте факты и материалы и выберите нужный документ. После оплаты и подтверждения администратором KORGAN подготовит документ и сохранит его в «Мои дела».'",
  )
  .replace(
    "helpText: 'Іс құрыңыз, фактілер мен материалдарды қосыңыз, AI‑заңгерге сұрақ қойыңыз. Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады. Құжат төлемі қосылса, генерация төлем мен қолмен растаудан бұрын басталмайды.'",
    "helpText: 'Іс құрып, фактілер мен материалдарды қосыңыз және қажетті құжатты таңдаңыз. Төлем әкімшімен расталғаннан кейін KORGAN құжатты дайындап, «Менің істерім» бөлімінде сақтайды.'",
  )
  .replaceAll('Mini App использует отдельный API и не изменяет production Telegram‑агента.', 'Материалы MiniApp используются только для подготовки документов и управления делами.')
  .replaceAll('Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', 'MiniApp материалдары тек құжат дайындау және істерді басқару үшін пайдаланылады.');

writeFileSync(mainFile, source, 'utf8');
