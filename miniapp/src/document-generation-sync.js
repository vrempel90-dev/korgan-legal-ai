import './document-generation-sync.css';

/*
 * Document progress must never outrun the backend.
 * Steps 1-4 are an indicative UX while one real HTTP request is running.
 * Step 5 and 100% are authoritative: they are shown only after the server has
 * returned a complete released DOCX payload. No global toast/MutationObserver.
 */
const upstreamFetch = window.fetch.bind(window);

const RUN_PATH = /\/miniapp\/documents\/generate$/;
const PAID_RUN_PATH = /\/miniapp\/documents\/payments\/[^/]+\/(?:retry|receipt|receipt-url)$/;

let lastCaseId = '';
let currentRun = null;

const COPY = {
  ru: {
    kicker: 'ПОДГОТОВКА ДОКУМЕНТА',
    title: 'Юридический workflow',
    readyTitle: 'Документ готов',
    failedTitle: 'Подготовка не завершена',
    readyToast: 'Документ готов и сохранён в «Мои дела».',
    caption: 'Этапы 1–4 показывают ход обработки. 100% появляется только после фактической готовности DOCX на сервере.',
    readyCaption: 'DOCX сформирован и сервер подтвердил его готовность.',
    failedCaption: 'Документ не помечен готовым. Повторите подготовку после устранения ошибки.',
    done: 'Готово',
    active: 'В работе',
    waiting: 'Ожидает',
    steps: [
      'Проверка фактов и сторон',
      'Определение подсудности',
      'Анализ законодательства РК',
      'Формирование требований и документа',
      'Финальная проверка качества',
    ],
  },
  kk: {
    kicker: 'ҚҰЖАТТЫ ДАЙЫНДАУ',
    title: 'Заңдық workflow',
    readyTitle: 'Құжат дайын',
    failedTitle: 'Дайындау аяқталмады',
    readyToast: 'Құжат дайын және «Менің істерім» бөлімінде сақталды.',
    caption: '1–4 кезең өңдеу барысын көрсетеді. 100% тек DOCX серверде нақты дайын болғаннан кейін көрсетіледі.',
    readyCaption: 'DOCX жасалды және сервер оның дайын екенін растады.',
    failedCaption: 'Құжат дайын деп белгіленбеді. Қатені жойғаннан кейін қайта дайындаңыз.',
    done: 'Дайын',
    active: 'Орындалуда',
    waiting: 'Күтуде',
    steps: [
      'Фактілер мен тараптарды тексеру',
      'Соттылықты анықтау',
      'ҚР заңнамасын талдау',
      'Талаптар мен құжатты қалыптастыру',
      'Сапаны финалдық тексеру',
    ],
  },
};

function isKazakh() {
  try {
    const raw = localStorage.getItem('korgan-miniapp-state-v1');
    const state = raw ? JSON.parse(raw) : null;
    return state?.language === 'kk' || document.documentElement.lang === 'kk';
  } catch {
    return document.documentElement.lang === 'kk';
  }
}

function copy() {
  return COPY[isKazakh() ? 'kk' : 'ru'];
}

function normalize(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase('ru-RU');
}

function requestUrl(input) {
  try {
    return new URL(typeof input === 'string' ? input : input?.url || '', window.location.origin);
  } catch {
    return null;
  }
}

function rememberCase(value) {
  const clean = String(value || '').trim();
  if (clean && clean !== 'undefined' && clean !== 'null') lastCaseId = clean;
}

function captureCaseFromRequest(url, init) {
  if (!url) return;
  const match = url.pathname.match(/\/miniapp\/cases\/([^/]+)/);
  if (match) rememberCase(decodeURIComponent(match[1]));
  if (RUN_PATH.test(url.pathname) && typeof init?.body === 'string') {
    try { rememberCase(JSON.parse(init.body)?.case_id); } catch {}
  }
}

function caseFromVisibleHeader() {
  const header = document.querySelector('.app-shell .subbar strong')?.textContent || '';
  const match = header.match(/KOR-[A-Z0-9-]+/i);
  return match ? match[0].toUpperCase() : '';
}

function isGenerationRequest(url, init) {
  if (!url) return false;
  const method = String(init?.method || 'GET').toUpperCase();
  return method === 'POST' && (RUN_PATH.test(url.pathname) || PAID_RUN_PATH.test(url.pathname));
}

function isCompleteDocument(payload) {
  return Boolean(
    payload
    && typeof payload.filing_ready === 'boolean'
    && ['verified', 'preliminary'].includes(payload.release_status)
    && typeof payload.document_base64 === 'string'
    && payload.document_base64.length > 32
    && typeof payload.filename === 'string'
    && payload.filename.trim()
  );
}

function findGenerationButton() {
  const labels = [
    'подготовить документ',
    'повторить подготовку без оплаты',
    'құжат дайындау',
    'құжатты дайындау',
    'төлемсіз қайта дайындау',
  ];
  return Array.from(document.querySelectorAll('main button')).find((button) => {
    const text = normalize(button.textContent);
    return labels.some((label) => text.includes(label));
  }) || null;
}

function buildProgress(caseId) {
  const c = copy();
  const panel = document.createElement('section');
  panel.className = 'korgan-generation-sync';
  panel.dataset.caseId = caseId || '';

  const head = document.createElement('div');
  head.className = 'korgan-generation-sync-head';
  const headCopy = document.createElement('div');
  const kicker = document.createElement('span');
  kicker.textContent = c.kicker;
  const title = document.createElement('strong');
  title.className = 'korgan-generation-title';
  title.textContent = c.title;
  headCopy.append(kicker, title);
  const percent = document.createElement('div');
  percent.className = 'korgan-generation-percent';
  percent.textContent = '8%';
  head.append(headCopy, percent);

  const track = document.createElement('div');
  track.className = 'korgan-generation-track';
  const bar = document.createElement('div');
  bar.className = 'korgan-generation-bar';
  track.appendChild(bar);

  const steps = document.createElement('div');
  steps.className = 'korgan-generation-steps';
  c.steps.forEach((label, index) => {
    const row = document.createElement('div');
    row.className = `korgan-generation-step${index === 0 ? ' is-active' : ''}`;
    row.dataset.step = String(index + 1);
    const badge = document.createElement('div');
    badge.className = 'korgan-generation-step-index';
    badge.textContent = String(index + 1);
    const text = document.createElement('div');
    text.className = 'korgan-generation-step-label';
    text.textContent = label;
    const state = document.createElement('div');
    state.className = 'korgan-generation-step-state';
    state.textContent = index === 0 ? c.active : c.waiting;
    row.append(badge, text, state);
    steps.appendChild(row);
  });

  const caption = document.createElement('p');
  caption.className = 'korgan-generation-caption';
  caption.textContent = c.caption;

  panel.append(head, track, steps, caption);
  return panel;
}

function mountProgress(caseId) {
  const old = document.querySelector('.korgan-generation-sync');
  if (old) old.remove();

  const button = findGenerationButton();
  const page = button?.closest('main') || document.querySelector('main.page, main.payment-page');
  if (!page) return null;

  const panel = buildProgress(caseId);
  if (button?.parentElement === page) page.insertBefore(panel, button);
  else page.appendChild(panel);
  return panel;
}

function clearTimers(run) {
  (run?.timers || []).forEach((timer) => window.clearTimeout(timer));
  if (run) run.timers = [];
}

function renderPhase(run, activeIndex, percent) {
  if (!run?.panel?.isConnected) return;
  const c = copy();
  const rows = Array.from(run.panel.querySelectorAll('.korgan-generation-step'));
  rows.forEach((row, index) => {
    const badge = row.querySelector('.korgan-generation-step-index');
    const state = row.querySelector('.korgan-generation-step-state');
    row.classList.toggle('is-done', index < activeIndex);
    row.classList.toggle('is-active', index === activeIndex);
    if (badge) badge.textContent = index < activeIndex ? '✓' : String(index + 1);
    if (state) state.textContent = index < activeIndex ? c.done : index === activeIndex ? c.active : c.waiting;
  });
  const bar = run.panel.querySelector('.korgan-generation-bar');
  const label = run.panel.querySelector('.korgan-generation-percent');
  if (bar) bar.style.width = `${percent}%`;
  if (label) label.textContent = `${percent}%`;
}

function beginGeneration(caseId) {
  if (currentRun) {
    clearTimers(currentRun);
    currentRun.panel?.remove();
  }
  const resolvedCase = caseId || caseFromVisibleHeader() || lastCaseId;
  rememberCase(resolvedCase);
  const run = {
    caseId: resolvedCase,
    panel: mountProgress(resolvedCase),
    timers: [],
    finished: false,
  };
  currentRun = run;
  renderPhase(run, 0, 8);

  const schedule = (ms, index, percent) => {
    run.timers.push(window.setTimeout(() => {
      if (!run.finished && currentRun === run) renderPhase(run, index, percent);
    }, ms));
  };
  schedule(900, 1, 26);
  schedule(3200, 2, 48);
  schedule(7200, 3, 70);
  /* Step 5 may become active, but it is never marked done by a timer. */
  schedule(13000, 4, 88);
  return run;
}

function cancelGeneration(run) {
  if (!run || currentRun !== run) return;
  clearTimers(run);
  run.finished = true;
  run.panel?.remove();
  currentRun = null;
}

function failGeneration(run) {
  if (!run || currentRun !== run) return;
  clearTimers(run);
  run.finished = true;
  const c = copy();
  if (run.panel?.isConnected) {
    run.panel.classList.add('is-error');
    const title = run.panel.querySelector('.korgan-generation-title');
    const percent = run.panel.querySelector('.korgan-generation-percent');
    const caption = run.panel.querySelector('.korgan-generation-caption');
    if (title) title.textContent = c.failedTitle;
    if (percent) percent.textContent = '—';
    if (caption) caption.textContent = c.failedCaption;
  }
  window.setTimeout(() => {
    if (currentRun === run) currentRun = null;
    run.panel?.remove();
  }, 4200);
}

function hapticSuccess() {
  try { window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.('success'); } catch {}
}

function mountReadySnackbar(caseId) {
  const readyPage = document.querySelector('.ready-page');
  const shell = readyPage?.closest('.app-shell');
  if (!readyPage || !shell) return false;
  if (shell.querySelector('.korgan-ready-snackbar')) return true;

  const toast = document.createElement('div');
  toast.className = 'korgan-ready-snackbar';
  toast.dataset.caseId = caseId || '';
  toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', 'polite');
  const icon = document.createElement('div');
  icon.className = 'korgan-ready-snackbar-icon';
  icon.textContent = '✓';
  const text = document.createElement('div');
  text.textContent = copy().readyToast;
  toast.append(icon, text);
  shell.appendChild(toast);
  hapticSuccess();

  window.setTimeout(() => {
    if (!toast.isConnected) return;
    toast.classList.add('is-leaving');
    window.setTimeout(() => toast.remove(), 170);
  }, 3000);
  return true;
}

function scheduleReadySnackbar(caseId) {
  const started = Date.now();
  const timer = window.setInterval(() => {
    if (mountReadySnackbar(caseId) || Date.now() - started > 5000) {
      window.clearInterval(timer);
    }
  }, 80);
}

async function completeGeneration(run) {
  if (!run || currentRun !== run) return;
  clearTimers(run);
  run.finished = true;
  const c = copy();
  if (run.panel?.isConnected) {
    const rows = Array.from(run.panel.querySelectorAll('.korgan-generation-step'));
    rows.forEach((row, index) => {
      row.classList.remove('is-active');
      row.classList.add('is-done');
      const badge = row.querySelector('.korgan-generation-step-index');
      const state = row.querySelector('.korgan-generation-step-state');
      if (badge) badge.textContent = '✓';
      if (state) state.textContent = c.done;
    });
    const bar = run.panel.querySelector('.korgan-generation-bar');
    const percent = run.panel.querySelector('.korgan-generation-percent');
    const title = run.panel.querySelector('.korgan-generation-title');
    const caption = run.panel.querySelector('.korgan-generation-caption');
    if (bar) bar.style.width = '100%';
    if (percent) percent.textContent = '100%';
    if (title) title.textContent = c.readyTitle;
    if (caption) caption.textContent = c.readyCaption;
  }
  scheduleReadySnackbar(run.caseId);
  /* Let the user see the authoritative fifth-step completion before React moves
     to the ready screen. The document is already complete at this point. */
  await new Promise((resolve) => window.setTimeout(resolve, 220));
  if (currentRun === run) currentRun = null;
}

window.fetch = async function korganGenerationSynchronizedFetch(input, init) {
  const url = requestUrl(input);
  captureCaseFromRequest(url, init);
  const tracked = isGenerationRequest(url, init);
  const run = tracked ? beginGeneration(lastCaseId || caseFromVisibleHeader()) : null;

  try {
    const response = await upstreamFetch(input, init);
    if (!tracked) return response;

    let payload = null;
    try { payload = await response.clone().json(); } catch {}
    rememberCase(payload?.case_id || payload?.case?.id || payload?.payment?.case_id);

    if (response.ok && payload?.payment_required) {
      cancelGeneration(run);
      return response;
    }
    if (response.ok && isCompleteDocument(payload)) {
      if (run) run.caseId = run.caseId || lastCaseId;
      await completeGeneration(run);
      return response;
    }

    failGeneration(run);
    return response;
  } catch (error) {
    failGeneration(run);
    throw error;
  }
};

/* A real user click gives the progress card the correct physical position before
   React flips the button into its busy state. Programmatic paid retries are still
   covered by the fetch wrapper above. */
document.addEventListener('click', (event) => {
  const button = event.target?.closest?.('button');
  if (!button || button.disabled) return;
  const text = normalize(button.textContent);
  if (![
    'подготовить документ',
    'повторить подготовку без оплаты',
    'құжат дайындау',
    'құжатты дайындау',
    'төлемсіз қайта дайындау',
  ].some((label) => text.includes(label))) return;
  rememberCase(caseFromVisibleHeader());
}, true);
