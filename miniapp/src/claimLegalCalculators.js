const APP_STATE_KEY = 'korgan-miniapp-state-v1';
const RECONCILE_MS = 250;
const ACTIVE_CLASS = 'claim-calculator-active';

const COPY = {
  ru: {
    launcher: 'Расчёт госпошлины и неустойки',
    dialog: 'Расчёт госпошлины и неустойки',
    subtitle: 'Рассчитайте нужную сумму и добавьте её прямо в описание иска.',
    guideTitle: 'Как пользоваться',
    steps: [
      'Сначала опишите вашу ситуацию в поле иска.',
      'Рассчитайте госпошлину или неустойку ниже.',
      'Под результатом нажмите «Добавить в иск».',
      'Сумма автоматически появится в поле с описанием иска. Закройте расчёт, проверьте текст и нажмите «Создать дело».',
    ],
    add: 'Добавить в иск',
    added: 'Добавлено в иск',
    addedHint: 'Готово. Сумма уже добавлена в описание иска. Закройте расчёт, проверьте текст и нажмите «Создать дело».',
    cannotAdd: 'Не удалось добавить сумму. Закройте расчёт и вернитесь к форме иска.',
    dutyHint: 'Укажите тип требования, кто подаёт иск и цену иска. Если у вас есть льгота по госпошлине, её нужно проверить отдельно.',
    penaltyHint: 'Укажите сумму долга и период просрочки. Если отдельная дата ставки вам неизвестна, оставьте это поле пустым.',
    dutyLine: amount => `Рассчитанная госпошлина для иска: ${amount}.`,
    penaltyLine: ({ amount, start, end, days }) => `Рассчитанная неустойка по статье 353 ГК РК: ${amount}${start && end ? ` за период с ${start} по ${end}` : ''}${days ? ` (${days} дн.)` : ''}.`,
  },
  kk: {
    launcher: 'Мемлекеттік баж бен тұрақсыздық айыбын есептеу',
    dialog: 'Мемлекеттік баж бен тұрақсыздық айыбын есептеу',
    subtitle: 'Қажетті соманы есептеп, оны талап сипаттамасына бірден қосыңыз.',
    guideTitle: 'Қалай пайдалану керек',
    steps: [
      'Алдымен талап өрісінде жағдайыңызды сипаттаңыз.',
      'Төменде мемлекеттік бажды немесе тұрақсыздық айыбын есептеңіз.',
      'Нәтиженің астындағы «Талапқа қосу» түймесін басыңыз.',
      'Сома талап сипаттамасына автоматты түрде қосылады. Есептеуді жауып, мәтінді тексеріп, «Іс құру» түймесін басыңыз.',
    ],
    add: 'Талапқа қосу',
    added: 'Талапқа қосылды',
    addedHint: 'Дайын. Сома талап сипаттамасына қосылды. Есептеуді жауып, мәтінді тексеріп, «Іс құру» түймесін басыңыз.',
    cannotAdd: 'Соманы қосу мүмкін болмады. Есептеуді жауып, талап нысанына оралыңыз.',
    dutyHint: 'Талап түрін, талап қоюшыны және талап бағасын көрсетіңіз. Егер мемлекеттік баж бойынша жеңілдік болса, оны бөлек тексеру қажет.',
    penaltyHint: 'Қарыз сомасын және кешігу кезеңін көрсетіңіз. Мөлшерлеме үшін жеке күнді білмесеңіз, өрісті бос қалдырыңыз.',
    dutyLine: amount => `Талап үшін есептелген мемлекеттік баж: ${amount}.`,
    penaltyLine: ({ amount, start, end, days }) => `ҚР АК 353-бабы бойынша есептелген тұрақсыздық айыбы: ${amount}${start && end ? `, ${start}–${end} кезеңі үшін` : ''}${days ? ` (${days} күн)` : ''}.`,
  },
};

function state() {
  try {
    return JSON.parse(globalThis.localStorage?.getItem(APP_STATE_KEY) || '{}');
  } catch {
    return {};
  }
}

function language() {
  return state()?.language === 'kk' ? 'kk' : 'ru';
}

function claimForm() {
  if (state()?.draft?.documentType !== 'claim') return null;
  const page = document.querySelector('#root main.creation-page');
  const textarea = page?.querySelector('textarea.case-input');
  if (!page || !textarea) return null;
  return { page, textarea, anchor: page.querySelector('.input-meta') || textarea };
}

function formatDate(raw) {
  const match = String(raw || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return String(raw || '');
  const [, year, month, day] = match;
  return `${day}.${month}.${year}`;
}

function setControlledTextarea(textarea, value) {
  const setter = Object.getOwnPropertyDescriptor(globalThis.HTMLTextAreaElement?.prototype || {}, 'value')?.set;
  if (setter) setter.call(textarea, value);
  else textarea.value = value;
  const event = typeof InputEvent === 'function'
    ? new InputEvent('input', { bubbles: true, inputType: 'insertText', data: null })
    : new Event('input', { bubbles: true });
  textarea.dispatchEvent(event);
}

function appendToClaim(line) {
  const form = claimForm();
  if (!form) return false;
  const current = String(form.textarea.value || '').trimEnd();
  if (current.includes(line)) return true;
  const next = `${current}${current ? '\n\n' : ''}${line}`;
  const max = Number(form.textarea.maxLength || 8000);
  if (max > 0 && next.length > max) return false;
  setControlledTextarea(form.textarea, next);
  return true;
}

function directText(box) {
  return Array.from(box?.childNodes || [])
    .filter(node => node.nodeType === Node.TEXT_NODE)
    .map(node => node.textContent || '')
    .join('')
    .trim();
}

function resultAmount(text, kind) {
  const pattern = kind === 'duty'
    ? /(?:Госпошлина|Мемлекеттік баж):\s*([^\n]+)/i
    : /(?:Неустойка|Тұрақсыздық айыбы):\s*([^\n]+)/i;
  return String(text || '').match(pattern)?.[1]?.trim() || '';
}

function resultDays(text) {
  return String(text || '').match(/(?:Дней|Күндер):\s*(\d+)/i)?.[1] || '';
}

function addResultAction(box, line, lang) {
  if (!box || !line || box.classList.contains('error')) return;
  box.querySelector('.claim-calculator-add')?.remove();
  box.querySelector('.claim-calculator-add-status')?.remove();
  const copy = COPY[lang];
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'claim-calculator-add';
  button.textContent = copy.add;
  const status = document.createElement('div');
  status.className = 'claim-calculator-add-status';
  button.addEventListener('click', () => {
    if (!appendToClaim(line)) {
      status.textContent = copy.cannotAdd;
      status.classList.add('error');
      return;
    }
    button.disabled = true;
    button.textContent = copy.added;
    status.textContent = copy.addedHint;
    status.classList.remove('error');
  });
  box.append(button, status);
}

function waitForCalculation(kind, submitted = {}) {
  const boxId = kind === 'duty' ? 'klt-duty-result' : 'klt-penalty-result';
  const box = document.getElementById(boxId);
  box?.classList.remove('show');
  box?.classList.remove('error');
  const started = Date.now();
  const timer = globalThis.setInterval?.(() => {
    const currentBox = document.getElementById(boxId);
    if (!currentBox || Date.now() - started > 32000) {
      globalThis.clearInterval?.(timer);
      return;
    }
    const text = directText(currentBox);
    if (!currentBox.classList.contains('show') || !text) return;
    globalThis.clearInterval?.(timer);
    if (currentBox.classList.contains('error')) return;
    const lang = language();
    const amount = resultAmount(text, kind);
    if (!amount) return;
    if (kind === 'duty') {
      addResultAction(currentBox, COPY[lang].dutyLine(amount), lang);
      return;
    }
    const start = formatDate(submitted.start);
    const end = formatDate(submitted.end);
    const days = resultDays(text);
    addResultAction(currentBox, COPY[lang].penaltyLine({ amount, start, end, days }), lang);
  }, 120);
}

function guide(copy, lang) {
  const article = document.createElement('article');
  article.className = 'claim-calculator-guide';
  article.dataset.language = lang;
  const title = document.createElement('h3');
  title.textContent = copy.guideTitle;
  const list = document.createElement('ol');
  for (const step of copy.steps) {
    const li = document.createElement('li');
    li.textContent = step;
    list.appendChild(li);
  }
  article.append(title, list);
  return article;
}

function preparePanel() {
  const backdrop = document.getElementById('korgan-legal-tools-backdrop');
  const sheet = backdrop?.querySelector('.korgan-legal-tools-sheet');
  if (!backdrop || !sheet) return;
  const lang = language();
  const copy = COPY[lang];
  backdrop.classList.add('claim-calculators-mode');
  const heading = sheet.querySelector('.korgan-legal-tools-head h2');
  const subtitle = sheet.querySelector('.korgan-legal-tools-head p');
  if (heading) heading.textContent = copy.dialog;
  if (subtitle) subtitle.textContent = copy.subtitle;
  const existingGuide = sheet.querySelector('.claim-calculator-guide');
  if (!existingGuide) {
    sheet.querySelector('.korgan-legal-tools-head')?.insertAdjacentElement('afterend', guide(copy, lang));
  } else if (existingGuide.dataset.language !== lang) {
    existingGuide.replaceWith(guide(copy, lang));
  }
  const cards = sheet.querySelectorAll('.korgan-legal-tool-card');
  const dutyHint = cards[0]?.querySelector('.hint');
  const penaltyHint = cards[1]?.querySelector('.hint');
  if (dutyHint) dutyHint.textContent = copy.dutyHint;
  if (penaltyHint) penaltyHint.textContent = copy.penaltyHint;
}

function clearLauncherPosition(button) {
  for (const name of ['--claim-calc-left', '--claim-calc-top', '--claim-calc-width']) {
    button?.style.removeProperty(name);
  }
}

function positionLauncher(button, form) {
  const inputRect = form.textarea.getBoundingClientRect();
  const anchorRect = form.anchor.getBoundingClientRect();
  button.style.setProperty('--claim-calc-left', `${Math.round(inputRect.left + globalThis.scrollX)}px`);
  button.style.setProperty('--claim-calc-top', `${Math.round(anchorRect.bottom + globalThis.scrollY + 12)}px`);
  button.style.setProperty('--claim-calc-width', `${Math.round(inputRect.width)}px`);
}

function reconcile() {
  const button = document.getElementById('korgan-legal-tools-button');
  const form = claimForm();
  if (!button) return;
  if (!form) {
    document.body?.classList.remove(ACTIVE_CLASS);
    button.hidden = true;
    clearLauncherPosition(button);
    document.getElementById('korgan-legal-tools-backdrop')?.classList.remove('open');
    return;
  }
  const copy = COPY[language()];
  document.body?.classList.add(ACTIVE_CLASS);
  button.hidden = false;
  button.textContent = copy.launcher;
  button.classList.add('claim-calculator-launcher');
  // Keep the launcher owned by the body-level Legal Workspace. We only position
  // it over the claim form; moving it into React's disposable subtree would
  // orphan the backdrop and create duplicate IDs after navigation.
  positionLauncher(button, form);
  preparePanel();
}

function install() {
  document.addEventListener('click', event => {
    const id = event.target?.id;
    if (id === 'korgan-legal-tools-button') globalThis.setTimeout?.(preparePanel, 0);
    if (id === 'klt-duty-submit') waitForCalculation('duty');
    if (id === 'klt-penalty-submit') {
      const submitted = {
        start: document.getElementById('klt-penalty-start')?.value || '',
        end: document.getElementById('klt-penalty-end')?.value || '',
      };
      waitForCalculation('penalty', submitted);
    }
  }, true);
  reconcile();
  globalThis.setInterval?.(reconcile, RECONCILE_MS);
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
}
