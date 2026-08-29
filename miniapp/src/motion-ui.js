/* KORGAN document workflow + professional motion layer.
   Background document generation is isolated per case. UI work is event-driven
   so Telegram WebView is not forced to rescan the page continuously. */

import { korganApi } from './korganApi';

const RU = {
  kicker: 'ПОДГОТОВКА ДОКУМЕНТА', title: 'Юридический workflow', pending: 'Ожидает', active: 'В работе', done: 'Готово',
  note: 'Процент ориентировочный. Финальную готовность подтверждает сервер KORGAN после завершения проверок качества.',
  readyTitle: 'Документ готов', readyText: 'Документ подготовлен и сохранён в исходном деле. Можете открыть и просмотреть результат.',
  open: 'Открыть', download: 'Скачать DOCX', background: 'Документ готовится в фоне', alreadyRunning: 'Этот документ уже готовится',
  failedTitle: 'Подготовка не завершена', paymentTitle: 'Требуется оплата', paymentText: 'Откройте дело и продолжите через платёжный экран.',
};
const KK = {
  kicker: 'ҚҰЖАТТЫ ДАЙЫНДАУ', title: 'Заңдық workflow', pending: 'Күтуде', active: 'Орындалуда', done: 'Дайын',
  note: 'Пайыз шамамен көрсетіледі. Соңғы дайындықты KORGAN сервері сапа тексерулері аяқталғаннан кейін растайды.',
  readyTitle: 'Құжат дайын', readyText: 'Құжат дайындалып, бастапқы істе сақталды. Нәтижені ашып, қарай аласыз.',
  open: 'Ашу', download: 'DOCX жүктеу', background: 'Құжат фонда дайындалуда', alreadyRunning: 'Бұл құжат қазірдің өзінде дайындалуда',
  failedTitle: 'Құжатты дайындау аяқталмады', paymentTitle: 'Төлем қажет', paymentText: 'Істі ашып, төлем экраны арқылы жалғастырыңыз.',
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

const PERCENTAGES = [10, 28, 50, 70, 88];
const STAGE_AFTER_MS = [0, 15000, 45000, 90000, 150000];
const POLL_MS = 8000;
const JOB_TIMEOUT_MS = 6 * 60 * 1000;
const jobs = new Map();
const paymentPassCases = new Set();
let observer = null;
let renderScheduled = false;

function storedLanguage() {
  try {
    const raw = localStorage.getItem('korgan-miniapp-state-v1');
    const state = raw ? JSON.parse(raw) : null;
    return state?.language === 'kk' ? 'kk' : 'ru';
  } catch {
    return 'ru';
  }
}

function isKazakh(text = '') {
  if (/[ӘәҒғҚқҢңӨөҰұҮүҺһІі]/.test(String(text || ''))) return true;
  return document.documentElement.lang === 'kk' || storedLanguage() === 'kk';
}
function copyFor(text = '') { return isKazakh(text) ? KK : RU; }

function inferProfile(text) {
  const value = String(text || '').toLowerCase();
  if (value.includes('исковое заявление') || value.includes('талап қою арызы')) return 'claim';
  if (value.includes('договор') || value.includes('шарт')) return 'contract';
  if (value.includes('отзыв на иск') || value.includes('талапқа пікір')) return 'response';
  if (value.includes('ответ на претензию') || value.includes('сотқа дейінгі талапқа жауап')) return 'pretrial_response';
  if (value.includes('досудебная претензия') || value.includes('сотқа дейінгі талап')) return 'pretrial';
  return 'generic';
}

function currentCasePage() {
  return Array.from(document.querySelectorAll('main.page')).find((page) => page.querySelector('.status-card')) || null;
}
function caseIdForPage(page) {
  const value = (page?.closest('.app-shell')?.querySelector('.subbar strong')?.textContent || '').trim();
  const match = value.match(/KOR-[A-Z0-9]+/i);
  return match ? match[0].toUpperCase() : '';
}
function headingForPage(page) { return (page?.querySelector('.analysis-card .card-head h2')?.textContent || '').trim(); }
function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (typeof text === 'string') node.textContent = text;
  return node;
}
function haptic(kind = 'success') {
  try {
    const api = window.Telegram?.WebApp?.HapticFeedback;
    if (kind === 'success') api?.notificationOccurred?.('success');
    else if (kind === 'error') api?.notificationOccurred?.('error');
    else api?.impactOccurred?.('light');
  } catch {}
}

function stageFor(job) {
  const elapsed = Math.max(0, Date.now() - job.startedAt);
  let stage = 0;
  STAGE_AFTER_MS.forEach((threshold, index) => { if (elapsed >= threshold) stage = index; });
  return Math.min(stage, 4);
}

function buildProgress(job) {
  const profile = PROFILES[job.profile] || PROFILES.generic;
  const steps = profile[job.language] || profile.ru;
  const panel = createElement('section', 'korgan-document-progress');
  panel.dataset.caseId = job.caseId;
  panel.setAttribute('aria-live', 'polite');
  const head = createElement('div', 'korgan-progress-head');
  const headCopy = createElement('div');
  headCopy.append(createElement('span', 'korgan-progress-kicker', job.copy.kicker));
  headCopy.append(createElement('div', 'korgan-progress-title', job.copy.title));
  head.append(headCopy, createElement('div', 'korgan-progress-percent', '≈ 10%'));
  const track = createElement('div', 'korgan-progress-track');
  track.append(createElement('div', 'korgan-progress-bar'));
  const list = createElement('div', 'korgan-progress-steps');
  steps.forEach((name, index) => {
    const row = createElement('div', 'korgan-progress-step');
    row.dataset.step = String(index);
    row.append(createElement('div', 'korgan-progress-index', String(index + 1)), createElement('div', 'korgan-progress-name', name), createElement('div', 'korgan-progress-state', job.copy.pending));
    list.append(row);
  });
  panel.append(head, track, list, createElement('div', 'korgan-progress-note', job.copy.note));
  return panel;
}

function updateProgress(panel, job) {
  const stage = stageFor(job);
  const percent = PERCENTAGES[stage];
  const percentNode = panel.querySelector('.korgan-progress-percent');
  const bar = panel.querySelector('.korgan-progress-bar');
  if (percentNode && percentNode.textContent !== `≈ ${percent}%`) percentNode.textContent = `≈ ${percent}%`;
  if (bar && bar.style.width !== `${percent}%`) bar.style.width = `${percent}%`;
  panel.querySelectorAll('.korgan-progress-step').forEach((row, index) => {
    const done = index < stage;
    const active = index === stage;
    row.classList.toggle('is-done', done);
    row.classList.toggle('is-active', active);
    const state = row.querySelector('.korgan-progress-state');
    const text = done ? job.copy.done : active ? job.copy.active : job.copy.pending;
    if (state && state.textContent !== text) state.textContent = text;
  });
}

function downloadBase64(base64, filename) {
  if (!base64) return;
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename || 'KORGAN_document.docx';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1200);
}

async function downloadJob(job) {
  try {
    let result = job.result;
    if (!result?.document_base64) result = await korganApi.getDocument(job.caseId);
    downloadBase64(result?.document_base64, result?.filename);
  } catch {
    showToast({ title: job.copy.failedTitle, text: job.caseId, tone: 'error' });
  }
}

function buildReadyCard(job, page) {
  const existingNativeDownload = Array.from(page.querySelectorAll('button')).some((button) => /скачать.*docx|дайын.*docx|docx.*жүктеу/i.test(button.textContent || ''));
  const card = createElement('section', 'korgan-inline-ready-card');
  card.dataset.caseId = job.caseId;
  const mark = createElement('div', 'korgan-inline-ready-mark', '✓');
  const text = createElement('div', 'korgan-inline-ready-copy');
  text.append(createElement('strong', '', job.copy.readyTitle), createElement('span', '', job.title || job.caseId));
  card.append(mark, text);
  if (!existingNativeDownload) {
    const button = createElement('button', 'korgan-inline-ready-action', job.copy.download);
    button.type = 'button';
    button.addEventListener('click', () => downloadJob(job));
    card.append(button);
  }
  return card;
}

function renderVisibleCase() {
  const page = currentCasePage();
  if (!page) return;
  const caseId = caseIdForPage(page);
  if (!caseId) return;
  const job = jobs.get(caseId);
  const generationButton = Array.from(page.querySelectorAll('button.primary.wide')).find((button) => !/создать/i.test(button.textContent || '')) || null;

  page.querySelectorAll('.korgan-document-progress, .korgan-inline-ready-card').forEach((node) => {
    const remove = !job || node.dataset.caseId !== caseId || (job.status === 'running' && node.classList.contains('korgan-inline-ready-card')) || (job.status !== 'running' && node.classList.contains('korgan-document-progress'));
    if (remove) node.remove();
  });
  if (!job) return;

  if (job.status === 'running') {
    let panel = page.querySelector(`.korgan-document-progress[data-case-id="${caseId}"]`);
    if (!panel && generationButton) {
      panel = buildProgress(job);
      generationButton.parentNode?.insertBefore(panel, generationButton);
    }
    if (panel) updateProgress(panel, job);
    if (generationButton) {
      generationButton.classList.add('korgan-background-running');
      if (generationButton.getAttribute('aria-label') !== job.copy.background) generationButton.setAttribute('aria-label', job.copy.background);
    }
    return;
  }

  if (generationButton) generationButton.classList.remove('korgan-background-running');
  if (job.status === 'ready' && !page.querySelector(`.korgan-inline-ready-card[data-case-id="${caseId}"]`) && generationButton) {
    generationButton.parentNode?.insertBefore(buildReadyCard(job, page), generationButton);
  }
}

function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  window.requestAnimationFrame(() => {
    renderScheduled = false;
    renderVisibleCase();
  });
}

function toastStack() {
  let stack = document.querySelector('.korgan-toast-stack');
  if (stack) return stack;
  stack = createElement('div', 'korgan-toast-stack');
  stack.setAttribute('aria-live', 'polite');
  document.body.append(stack);
  return stack;
}

function showToast({ title, text = '', action = '', onAction = null, tone = 'ready', persistent = false }) {
  const card = createElement('div', `korgan-doc-toast ${tone}`);
  const icon = createElement('div', 'korgan-toast-icon', tone === 'error' ? '!' : tone === 'payment' ? '₸' : '✓');
  const copy = createElement('div', 'korgan-toast-copy');
  copy.append(createElement('strong', '', title));
  if (text) copy.append(createElement('span', '', text));
  card.append(icon, copy);
  if (action && onAction) {
    const button = createElement('button', 'korgan-toast-action', action);
    button.type = 'button';
    button.addEventListener('click', async () => {
      await onAction();
      card.classList.add('is-leaving');
      window.setTimeout(() => card.remove(), 180);
    });
    card.append(button);
  }
  const stack = toastStack();
  stack.prepend(card);
  while (stack.children.length > 3) stack.lastElementChild?.remove();
  if (!persistent) window.setTimeout(() => {
    if (!card.isConnected) return;
    card.classList.add('is-leaving');
    window.setTimeout(() => card.remove(), 180);
  }, 11000);
  return card;
}

function waitFor(check, timeout = 4500) {
  const started = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      const value = check();
      if (value) return resolve(value);
      if (Date.now() - started >= timeout) return resolve(null);
      window.setTimeout(tick, 100);
    };
    tick();
  });
}

async function openCaseById(caseId) {
  const current = currentCasePage();
  if (current && caseIdForPage(current) === caseId) {
    scheduleRender();
    current.querySelector('.korgan-inline-ready-card, .status-card')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  const homeButton = document.querySelector('.bottom-nav button:nth-child(1)');
  if (homeButton instanceof HTMLButtonElement) homeButton.click();
  const casesCard = await waitFor(() => Array.from(document.querySelectorAll('.action-card')).find((button) => /мои дела|менің істерім/i.test(button.textContent || '')));
  if (!(casesCard instanceof HTMLElement)) return;
  casesCard.click();
  const caseButton = await waitFor(() => Array.from(document.querySelectorAll('.case-list-item')).find((button) => (button.textContent || '').includes(caseId)));
  if (!(caseButton instanceof HTMLElement)) return;
  caseButton.click();
  await waitFor(() => {
    const page = currentCasePage();
    return page && caseIdForPage(page) === caseId ? page : null;
  });
  scheduleRender();
}

function notifyReady(job) {
  haptic('success');
  showToast({ title: job.copy.readyTitle, text: job.copy.readyText, action: job.copy.open, onAction: () => openCaseById(job.caseId), tone: 'ready', persistent: true });
}

function stopJobTimers(job) {
  if (job.pollTimer) window.clearTimeout(job.pollTimer);
  if (job.progressTimer) window.clearInterval(job.progressTimer);
  job.pollTimer = null;
  job.progressTimer = null;
}

function finishReady(job, result) {
  if (job.status !== 'running') return;
  stopJobTimers(job);
  job.status = 'ready';
  job.result = result;
  job.finishedAt = Date.now();
  if (result?.title) job.title = result.title;
  scheduleRender();
  notifyReady(job);
}

function finishError(job, error) {
  if (job.status !== 'running') return;
  stopJobTimers(job);
  job.status = 'error';
  job.error = error;
  scheduleRender();
  haptic('error');
  showToast({ title: job.copy.failedTitle, text: error?.message || job.caseId, action: job.copy.open, onAction: () => openCaseById(job.caseId), tone: 'error' });
}

function finishPayment(job, result) {
  if (job.status !== 'running') return;
  stopJobTimers(job);
  jobs.delete(job.caseId);
  paymentPassCases.add(job.caseId);
  showToast({ title: job.copy.paymentTitle, text: job.copy.paymentText, action: job.copy.open, onAction: () => openCaseById(job.caseId), tone: 'payment', persistent: true });
  scheduleRender();
  return result;
}

function shouldWaitForServer(error) {
  const status = Number(error?.status || 0);
  return !status || status === 408 || status === 429 || status === 499 || status >= 500;
}

function scheduleDocumentPoll(job, delay = POLL_MS) {
  if (job.status !== 'running') return;
  job.pollTimer = window.setTimeout(async () => {
    if (job.status !== 'running') return;
    if (Date.now() - job.startedAt >= JOB_TIMEOUT_MS) {
      finishError(job, job.transportError || new Error(job.copy.failedTitle));
      return;
    }
    try {
      const result = await korganApi.getDocument(job.caseId);
      if (result?.document_base64) {
        finishReady(job, result);
        return;
      }
    } catch (error) {
      if (Number(error?.status || 0) !== 404 && !shouldWaitForServer(error)) {
        finishError(job, error);
        return;
      }
    }
    scheduleRender();
    scheduleDocumentPoll(job, POLL_MS);
  }, delay);
}

function startBackgroundJob({ caseId, documentType = 'claim', language = 'ru', title = '' }) {
  const existing = jobs.get(caseId);
  const copy = language === 'kk' ? KK : RU;
  if (existing?.status === 'running') {
    haptic('light');
    showToast({ title: copy.alreadyRunning, text: title || caseId, tone: 'info' });
    return existing.promise;
  }

  const job = {
    caseId, documentType, language, title: title || caseId, profile: inferProfile(title), copy,
    startedAt: Date.now(), status: 'running', result: null, error: null, transportError: null,
    promise: null, pollTimer: null, progressTimer: null,
  };
  jobs.set(caseId, job);
  haptic('light');
  scheduleRender();
  job.progressTimer = window.setInterval(scheduleRender, 5000);
  scheduleDocumentPoll(job, 10000);

  job.promise = korganApi.generateDocument(caseId, documentType, language)
    .then((result) => {
      if (job.status !== 'running') return result;
      if (result?.payment_required) return finishPayment(job, result);
      if (result?.document_base64 || result?.status === 'document_ready') finishReady(job, result);
      return result;
    })
    .catch((error) => {
      if (job.status !== 'running') return undefined;
      if (shouldWaitForServer(error)) {
        job.transportError = error;
        scheduleRender();
        return undefined;
      }
      finishError(job, error);
      return undefined;
    });

  job.promise.catch(() => {});
  return job.promise;
}

async function startPaidBackgroundJob(page) {
  const copy = copyFor(page.textContent || '');
  const orderText = page.querySelector('.section-kicker')?.textContent || '';
  const match = orderText.match(/#(\d+)/);
  if (!match) return;
  try {
    const status = await korganApi.documentPaymentStatus(match[1]);
    const payment = status?.payment;
    if (!payment?.case_id) throw new Error(copy.failedTitle);
    const language = isKazakh(page.textContent || '') ? 'kk' : 'ru';
    startBackgroundJob({ caseId: String(payment.case_id).toUpperCase(), documentType: payment.document_type || 'claim', language, title: payment.document_type || String(payment.case_id) });
    const back = page.closest('.app-shell')?.querySelector('.subbar .icon-btn');
    if (back instanceof HTMLButtonElement) back.click();
  } catch (error) {
    showToast({ title: copy.failedTitle, text: error?.message || '', tone: 'error' });
  }
}

function handleGenerationClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest('button.primary.wide');
  if (!(button instanceof HTMLButtonElement) || button.disabled) return;
  const page = button.closest('main.page');
  if (!page) return;

  if (page.classList.contains('payment-page') && /оплаченный документ|төленген құжат/i.test(button.textContent || '')) {
    event.preventDefault();
    event.stopImmediatePropagation();
    startPaidBackgroundJob(page);
    return;
  }
  if (!page.querySelector('.status-card')) return;
  const caseId = caseIdForPage(page);
  if (!caseId) return;
  if (/₸/.test(button.textContent || '') || paymentPassCases.has(caseId)) return;

  event.preventDefault();
  event.stopImmediatePropagation();
  const heading = headingForPage(page);
  const language = isKazakh(page.textContent || '') ? 'kk' : 'ru';
  startBackgroundJob({ caseId, documentType: inferProfile(heading), language, title: heading });
}

function start() {
  document.addEventListener('click', handleGenerationClick, true);
  observer = new MutationObserver(scheduleRender);
  const root = document.getElementById('root') || document.body;
  observer.observe(root, { childList: true, subtree: true });
  scheduleRender();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
