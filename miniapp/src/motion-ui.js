/* KORGAN motion UI enhancer.
   This file never intercepts or replaces React handlers/API calls.
   It only observes the existing document-generation button and renders an
   approximate workflow indicator while the real server request is running. */

const RU = {
  kicker: 'ПОДГОТОВКА ДОКУМЕНТА',
  title: 'Юридический workflow',
  pending: 'Ожидает',
  active: 'В работе',
  done: 'Готово',
  stopped: 'Остановлено',
  note: 'Процент ориентировочный. Финальную готовность подтверждает сервер KORGAN после завершения проверок качества.',
};

const KK = {
  kicker: 'ҚҰЖАТТЫ ДАЙЫНДАУ',
  title: 'Заңдық workflow',
  pending: 'Күтуде',
  active: 'Орындалуда',
  done: 'Дайын',
  stopped: 'Тоқтатылды',
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
  if (value.includes('ответ на претензию') || value.includes('сотқа дейінгі талапқа жауап')) return 'pretrial_response';
  if (value.includes('досудебная претензия') || value.includes('сотқа дейінгі талап')) return 'pretrial';
  if (value.includes('отзыв на иск') || value.includes('талапқа пікір')) return 'response';
  if (value.includes('договор') || value.includes('шарт')) return 'contract';
  if (value.includes('исковое заявление') || value.includes('талап қою арызы')) return 'claim';
  return 'generic';
}

function stopTimers() {
  if (!current) return;
  current.timers.forEach(window.clearTimeout);
  if (current.watch) window.clearInterval(current.watch);
  current.timers = [];
  current.watch = null;
}

function clearCurrent() {
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

function markStopped() {
  if (!current || !current.panel.isConnected) return;
  stopTimers();
  current.panel.classList.add('is-stopped');
  const active = current.rows.find(({ row }) => row.classList.contains('is-active'));
  if (active) active.state.textContent = current.copy.stopped;
}

function findGenerationButton(page) {
  if (!page?.isConnected) return null;
  if (page.querySelector('.status-card')) return page.querySelector('button.primary.wide');
  if (page.classList.contains('payment-page')) {
    return Array.from(page.querySelectorAll('button.primary.wide')).find(button => /оплаченный документ|төленген құжат/i.test(button.textContent || '')) || null;
  }
  return null;
}

function startProgress(page, anchor) {
  if (!page || !anchor) return;
  if (current) {
    current.panel?.remove();
    clearCurrent();
  }

  const pageText = page.textContent || '';
  const language = inferLanguage(pageText);
  const inferred = page.querySelector('.status-card') ? inferProfile(pageText) : lastProfile;
  const profileKey = inferred || 'generic';
  if (profileKey !== 'generic') lastProfile = profileKey;

  const ui = buildPanel(profileKey, language);
  anchor.parentNode?.insertBefore(ui.panel, anchor);
  current = { ...ui, page, startedAt: Date.now(), timers: [], watch: null };

  STEP_DELAYS.forEach((delay, index) => {
    const timer = window.setTimeout(() => renderStage(index), delay);
    current.timers.push(timer);
  });

  current.watch = window.setInterval(() => {
    if (!current) return;
    if (!current.page.isConnected || !current.panel.isConnected) {
      clearCurrent();
      return;
    }
    const liveButton = findGenerationButton(current.page);
    if (Date.now() - current.startedAt > 900 && liveButton && !liveButton.disabled && !liveButton.querySelector('.spin')) {
      markStopped();
    }
  }, 300);
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

  startProgress(page, button);
}, true);

const cleanupObserver = new MutationObserver(() => {
  if (current && (!current.page.isConnected || !current.panel.isConnected)) clearCurrent();
});
cleanupObserver.observe(document.documentElement, { childList: true, subtree: true });
