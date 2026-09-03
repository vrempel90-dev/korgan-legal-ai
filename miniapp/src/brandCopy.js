const REPLACEMENTS = new Map([
  ['KORGAN Legal AI', 'KORGAN'],
  ['KORGAN LEGAL AI', 'KORGAN'],
  ['Условия использования KORGAN Legal AI', 'Условия использования KORGAN'],
  ['KORGAN Legal AI пайдалану шарттары', 'KORGAN пайдалану шарттары'],
  ['Mini App использует отдельный API и не изменяет production Telegram‑агента.', 'Данные Mini App обрабатываются в отдельном защищённом production‑контуре KORGAN.'],
  ['Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.', 'Mini App деректері KORGAN-ның бөлек қорғалған production контурында өңделеді.'],
  ['Для документа KORGAN использует то же production‑юридическое ядро и quality gates, что и AI‑агент.', 'Для документа KORGAN использует production‑юридическое ядро и обязательные финальные проверки качества.'],
  ['Құжат үшін KORGAN AI‑агентпен бірдей production заңдық ядро мен quality gate-терді қолданады.', 'Құжат үшін KORGAN production заңдық ядросын және міндетті финалдық сапа тексерулерін қолданады.'],
]);

function replaceTextNode(node) {
  const value = String(node.textContent || '');
  let next = value;
  for (const [from, to] of REPLACEMENTS) next = next.split(from).join(to);
  if (next !== value) node.textContent = next;
}

function applyBrandCopy(root = document.getElementById('root')) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    replaceTextNode(node);
    node = walker.nextNode();
  }
}

applyBrandCopy();
document.addEventListener('click', () => window.setTimeout(() => applyBrandCopy(), 0), true);
window.setInterval(() => applyBrandCopy(), 500);
