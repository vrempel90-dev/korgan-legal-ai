import './generation-stage-timeline.css';
import { loadState } from './store.js';
import {
  clampProgress,
  stageIndexForProgress,
  timelineSignature,
} from './generationStageState.js';

const ROOT_ID = 'korgan-generation-stage-timeline';
const LIFECYCLE_EVENT = 'korgan:generation-lifecycle';
let stageKey = '';
let stageStartedAt = Date.now();
let elapsedTimer = null;

const COPY = {
  ru: {
    title: 'Этапы подготовки',
    live: 'Работа продолжается',
    current: 'Сейчас выполняется',
    stages: ['Старт', 'Право и проект', 'Проверка качества', 'Word', 'Готово'],
  },
  kk: {
    title: 'Дайындау кезеңдері',
    live: 'Жұмыс жалғасуда',
    current: 'Қазір орындалып жатыр',
    stages: ['Бастау', 'Құқық және жоба', 'Сапаны тексеру', 'Word', 'Дайын'],
  },
};

function languageFor(page, progress) {
  const text = `${page?.textContent || ''} ${progress?.getAttribute('aria-label') || ''}`;
  return /Құжат|Қазақстан|Дайындық|тексерілуде/.test(text) ? 'kk' : 'ru';
}

function isClaimFlow() {
  try {
    return loadState()?.draft?.documentType === 'claim';
  } catch {
    return false;
  }
}

function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function updateElapsed() {
  const root = document.getElementById(ROOT_ID);
  const target = root?.querySelector('[data-generation-elapsed]');
  if (!target) return;
  target.textContent = formatElapsed(Date.now() - stageStartedAt);
}

function ensureElapsedTimer() {
  if (elapsedTimer) return;
  elapsedTimer = window.setInterval(updateElapsed, 1000);
}

function stopElapsedTimer() {
  if (!elapsedTimer) return;
  window.clearInterval(elapsedTimer);
  elapsedTimer = null;
}

function renderTimeline(page, progress) {
  if (!page || !progress) return null;

  const language = languageFor(page, progress);
  const copy = COPY[language];
  const value = clampProgress(progress.getAttribute('aria-valuenow'));
  const active = stageIndexForProgress(value);
  const failed = /Подготовка не завершилась|Дайындау аяқталмады/.test(page.textContent || '');
  const currentStage = String(progress.getAttribute('aria-label') || copy.stages[active] || '').trim();
  const nextStageKey = `${language}|${active}|${currentStage}`;
  if (nextStageKey !== stageKey) {
    stageKey = nextStageKey;
    stageStartedAt = Date.now();
  }
  const signature = `${timelineSignature({ language, progress: value, failed })}|${currentStage}`;

  let root = document.getElementById(ROOT_ID);
  // Never reuse a manually injected node from an old React screen. That was the
  // reason the claim timeline could remain on Home after navigation.
  if (root && root.parentElement !== page) {
    root.remove();
    root = null;
  }
  if (!root) {
    root = document.createElement('section');
    root.id = ROOT_ID;
    root.className = 'korgan-generation-stage-timeline';
    progress.insertAdjacentElement('afterend', root);
  }

  root.style.setProperty('--generation-progress', `${value}%`);
  root.style.setProperty('--generation-line-progress', `${Math.min(value * 0.8, 80)}%`);
  root.dataset.progress = String(value);

  if (root.dataset.signature !== signature) {
    root.dataset.signature = signature;
    root.innerHTML = `
      <div class="korgan-generation-stage-title">
        <strong>${copy.title}</strong>
        <span class="korgan-generation-live"><i aria-hidden="true"></i>${failed ? (language === 'kk' ? 'Қате' : 'Ошибка') : copy.live}</span>
      </div>
      <div class="korgan-generation-current">
        <span>${copy.current}</span>
        <strong>${currentStage || copy.stages[active]}</strong>
        <small data-generation-elapsed>${formatElapsed(Date.now() - stageStartedAt)}</small>
      </div>
      <div class="korgan-generation-stage-track" aria-label="${copy.title}">
        <span class="korgan-generation-stage-line" aria-hidden="true"></span>
        <span class="korgan-generation-stage-line-fill" aria-hidden="true"></span>
        ${copy.stages.map((label, index) => {
          const state = index < active ? 'is-done' : index === active ? (failed ? 'is-failed' : 'is-active') : '';
          const marker = index < active ? '✓' : index === active && !failed ? '•' : String(index + 1);
          return `<div class="korgan-generation-stage ${state}">
            <span class="korgan-generation-stage-dot">${marker}</span>
            <span class="korgan-generation-stage-label">${label}</span>
          </div>`;
        }).join('')}
      </div>`;
  }

  if (!failed && value < 100) ensureElapsedTimer();
  else stopElapsedTimer();
  updateElapsed();
  return root;
}

function sync() {
  const page = document.querySelector('main.ready-page');
  const progress = page?.querySelector('[role="progressbar"]');
  const root = document.getElementById(ROOT_ID);

  // The stage timeline is a claim-only UI. It must disappear immediately on
  // Home, consultation, contracts and every other document flow.
  if (!isClaimFlow() || !page || !progress) {
    root?.remove();
    stopElapsedTimer();
    stageKey = '';
    return;
  }

  renderTimeline(page, progress);
}

function install() {
  let scheduled = false;
  const scheduleSync = () => {
    if (scheduled) return;
    scheduled = true;
    const run = () => {
      scheduled = false;
      sync();
    };
    if (typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(run);
    else window.setTimeout(run, 0);
  };

  // Lifecycle events update real backend progress. A capture-phase click queues
  // one post-React sync for navigation, so stale claim UI is removed without
  // continuously watching or scanning the page.
  window.addEventListener(LIFECYCLE_EVENT, scheduleSync);
  window.addEventListener('pageshow', scheduleSync);
  document.addEventListener('click', scheduleSync, true);
  window.addEventListener('popstate', scheduleSync);
  scheduleSync();

  return () => {
    window.removeEventListener(LIFECYCLE_EVENT, scheduleSync);
    window.removeEventListener('pageshow', scheduleSync);
    document.removeEventListener('click', scheduleSync, true);
    window.removeEventListener('popstate', scheduleSync);
    stopElapsedTimer();
    document.getElementById(ROOT_ID)?.remove();
  };
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') install();
