/* KORGAN motion UI enhancer.
   Presentation only: existing React handlers/API calls are never replaced.
   Workflow exists only inside the concrete case/payment screen while the real
   generation request is busy, then it is removed immediately. */

const RU = {
  kicker: 'ПОДГОТОВКА ДОКУМЕНТА', title: 'Юридический workflow',
  pending: 'Ожидает', active: 'В работе', done: 'Готово',
  note: 'Процент ориентировочный. Финальную готовность подтверждает сервер KORGAN после завершения проверок качества.',
};
const KK = {
  kicker: 'ҚҰЖАТТЫ ДАЙЫНДАУ', title: 'Заңдық workflow',
  pending: 'Күтуде', active: 'Орындалуда', done: 'Дайын',
  note: 'Пайыз шамамен көрсетіледі. Соңғы дайындықты KORGAN сервері сапа тексерулері аяқталғаннан кейін растайды.',
};

const PROFILES = {
  claim: {
    ru: ['Проверка фактов и сторон', 'Определение подсудности', 'Анализ законодательства РК', 'Формирование требований и иска', 'Финальная проверка качества'],
    kk: ['Фактілер мен тараптарды тексеру', 'Соттылықты анықтау', 'ҚР заңнамасын талдау', 'Талаптар мен талап арызды қалыптастыру', 'Сапаны соңғы тексеру'],
  },
  contract: {
    ru: ['Проверка сторон и предмета', 'Анализ условий и рисков', 'Проверка законодательства РК', 'Формирование условий договора', 'Финальная проверка качества'],
    kk: ['Тараптар мен шарт мәнін тексеру', 'Талаптар мен тәуекелдерді талдау', 'ҚР заңнамасын тексеру', 'Шарт талаптарын қалыптастыру', 'Сапаны соңғы тексеру'],
  },
  response: {
    ru: ['Разбор требований истца', 'Проверка фактов и доказательств', 'Анализ правовой позиции', 'Формирование возражений и отзыва', 'Финальная проверка качества'],
    kk: ['Талап қоюшы талаптарын талдау', 'Фактілер мен дәлелдемелерді тексеру', 'Құқықтық ұстанымды талдау', 'Қарсылықтар мен пікірді қалыптастыру', 'Сапаны соңғы тексеру'],
  },
  pretrial: {
    ru: ['Фиксация нарушения', 'Проверка правовых оснований', 'Расчёт и формирование требований', 'Подготовка текста претензии', 'Финальная проверка качества'],
    kk: ['Бұзушылықты белгілеу', 'Құқықтық негіздерді тексеру', 'Талаптарды есептеу және қалыптастыру', 'Сотқа дейінгі талап мәтінін дайындау', 'Сапаны соңғы тексеру'],
  },
  pretrial_response: {
    ru: ['Разбор требований претензии', 'Проверка фактов и документов', 'Анализ правовой позиции', 'Формирование ответа на претензию', 'Финальная проверка качества'],
    kk: ['Талап мазмұнын талдау', 'Фактілер мен құжаттарды тексеру', 'Құқықтық ұстанымды талдау', 'Сотқа дейінгі талапқа жауап дайындау', 'Сапаны соңғы тексеру'],
  },
  generic: {
    ru: ['Проверка исходных данных', 'Анализ законодательства РК', 'Формирование юридической структуры', 'Подготовка текста документа', 'Финальная проверка качества'],
    kk: ['Бастапқы деректерді тексеру', 'ҚР заңнамасын талдау', 'Құқықтық құрылымды қалыптастыру', 'Құжат мәтінін дайындау', 'Сапаны соңғы тексеру'],
  },
};

const PERCENTAGES = [12, 32, 54, 74, 88];
const STEP_DELAYS = [0, 2400, 5200, 8500, 12200];
let current = null;
let lastProfile = 'generic';

function inferLanguage(text) {
  return /[ӘәҒғҚқҢңӨөҰұҮүҺһІі]/.test(text || '') ? 'kk' : 'ru';
}

function inferProfile(text) {
  const value = String(text || '').toLowerCase();
  if (value.includes('исковое заявление') || value.includes('талап қою арызы')) return 'claim';
  if (value.includes('договор') || value.includes('шарт')) return 'contract';
  if (value.includes('отзыв на иск') || value.includes('талапқа пікір')) return 'response';
  if (value.includes('ответ на претензию') || value.includes('сотқа дейінгі талапқа жауап')) return 'pretrial_response';
  if (value.includes('досудебная претензия') || value.includes('сотқа дейінгі талап')) return 'pretrial';
  return 'generic';
}

function stopTimers() {
  if (!current) return;
  current.timers.forEach(window.clearTimeout);
  if (current.watch) window.clearInterval(current.watch);
  current.timers = [];
  current.watch = null;
}

function clearCurrent({ remove = false } = {}) {
  if (!current) return;
  if (remove) current.panel?.remove();
  stopTimers();
  current = null;
}

function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (typeof text === 'string') node.textContent = text;
  return node;
}

function buildPanel(profileKey, language) {
  const copy = language === 'kk' ? KK : RU;
  const profile = PROFILES[profileKey] || PROFILES.generic;
  const steps = profile[language] || profile.ru;
  const panel = createElement('section', 'korgan-document-progress');
  panel.setAttribute('aria-live', 'polite');
  panel.setAttribute('aria-label', copy.title);

  const head = createElement('div', 'korgan-progress-head');
  const headCopy = createElement('div');
  headCopy.append(createElement('span', 'korgan-progress-kicker', copy.kicker));
  headCopy.append(createElement('div', 'korgan-progress-title', copy.title));
  const percent = createElement('div', 'korgan-progress-percent', '≈ 12%');
  head.append(headCopy, percent);

  const track = createElement('div', 'korgan-progress-track');
  const bar = createElement('div', 'korgan-progress-bar');
  track.append(bar);

  const stepList = createElement('div', 'korgan-progress-steps');
  const rows = steps.map((name, index) => {
    const row = createElement('div', 'korgan-progress-step');
    const number = createElement('div', 'korgan-progress-index', String(index + 1));
    const label = createElement('div', 'korgan-progress-name', name);
    const state = createElement('div', 'korgan-progress-state', copy.pending);
    row.append(number, label, state);
    stepList.append(row);
    return { row, state };
  });

  const note = createElement('div', 'korgan-progress-note', copy.note);
  panel.append(head, track, stepList, note);
  return { panel, percent, bar, rows, copy };
}

function renderStage(stage) {
  if (!current) return;
  const capped = Math.max(0, Math.min(stage, current.rows.length - 1));
  current.percent.textContent = `≈ ${PERCENTAGES[capped]}%`;
  current.bar.style.width = `${PERCENTAGES[capped]}%`;
  current.rows.forEach(({ row, state }, index) => {
    row.classList.toggle('is-done', index < capped);
    row.classList.toggle('is-active', index === capped);
    state.textContent = index < capped ? current.copy.done : index === capped ? current.copy.active : current.copy.pending;
  });
}

function validContext(item) {
  if (!item?.page?.isConnected || !item?.panel?.isConnected) return false;
  if (item.kind === 'case') return Boolean(item.page.querySelector('.status-card'));
  if (item.kind === 'payment') return item.page.classList.contains('payment-page');
  return false;
}

function findGenerationButton(page, kind) {
  if (!page?.isConnected) return null;
  if (kind === 'case') return page.querySelector('.status-card') ? page.querySelector('button.primary.wide') : null;
  if (kind === 'payment' && page.classList.contains('payment-page')) {
    return Array.from(page.querySelectorAll('button.primary.wide')).find(button => /оплаченный документ|төленген құжат/i.test(button.textContent || '')) || null;
  }
  return null;
}

function startProgress(page, anchor, kind) {
  clearCurrent({ remove: true });

  const language = inferLanguage(page.textContent || '');
  const documentHeading = kind === 'case'
    ? (page.querySelector('.analysis-card .card-head h2')?.textContent || '')
    : '';
  const inferred = kind === 'case' ? inferProfile(documentHeading) : lastProfile;
  const profileKey = inferred || 'generic';
  if (profileKey !== 'generic') lastProfile = profileKey;

  const ui = buildPanel(profileKey, language);
  anchor.parentNode?.insertBefore(ui.panel, anchor);
  current = { ...ui, page, kind, startedAt: Date.now(), timers: [], watch: null };

  STEP_DELAYS.forEach((delay, index) => {
    current.timers.push(window.setTimeout(() => renderStage(index), delay));
  });

  current.watch = window.setInterval(() => {
    if (!current) return;
    if (!validContext(current)) {
      clearCurrent({ remove: true });
      return;
    }
    const liveButton = findGenerationButton(current.page, current.kind);
    if (Date.now() - current.startedAt > 900 && liveButton && !liveButton.disabled && !liveButton.querySelector('.spin')) {
      clearCurrent({ remove: true });
    }
  }, 250);
}

document.addEventListener('click', event => {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest('button.primary.wide');
  if (!button || button.disabled) return;
  const page = button.closest('main.page');
  if (!page) return;

  const caseGeneration = Boolean(page.querySelector('.status-card'));
  const paidGeneration = page.classList.contains('payment-page') && /оплаченный документ|төленген құжат/i.test(button.textContent || '');
  if (!caseGeneration && !paidGeneration) return;
  startProgress(page, button, caseGeneration ? 'case' : 'payment');
}, true);

const cleanupObserver = new MutationObserver(() => {
  if (current && !validContext(current)) clearCurrent({ remove: true });
});
cleanupObserver.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
