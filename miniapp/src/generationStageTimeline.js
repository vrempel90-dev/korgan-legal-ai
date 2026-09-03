import './generation-stage-timeline.css';
import { loadState } from './store.js';
import {
  clampProgress,
  stageIndexForProgress,
  timelineSignature,
} from './generationStageState.js';

const ROOT_ID = 'korgan-generation-stage-timeline';
const LIFECYCLE_EVENT = 'korgan:generation-lifecycle';

const COPY = {
  ru: {
    title: 'Этапы подготовки',
    live: 'Идёт реальная обработка',
    stages: ['Старт', 'Право и проект', 'Проверка качества', 'Word', 'Готово'],
  },
  kk: {
    title: 'Дайындау кезеңдері',
    live: 'Нақты өңдеу жүріп жатыр',
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

function renderTimeline(page, progress) {
  if (!page || !progress) return null;

  const language = languageFor(page, progress);
  const copy = COPY[language];
  const value = clampProgress(progress.getAttribute('aria-valuenow'));
  const active = stageIndexForProgress(value);
  const failed = /Подготовка не завершилась|Дайындау аяқталмады/.test(page.textContent || '');
  const signature = timelineSignature({ language, progress: value, failed });

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

  if (root.dataset.signature === signature) return root;
  root.dataset.signature = signature;

  root.innerHTML = `
    <div class="korgan-generation-stage-title">
      <strong>${copy.title}</strong>
      <span>${failed ? (language === 'kk' ? 'Қате' : 'Ошибка') : copy.live}</span>
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

  // generationJob publishes this event from the real backend job. React screen
  // changes themselves do not publish it, so observe DOM navigation too; this
  // guarantees an injected timeline is removed as soon as the user leaves the
  // claim generation screen.
  window.addEventListener(LIFECYCLE_EVENT, scheduleSync);
  window.addEventListener('pageshow', scheduleSync);
  const observer = typeof MutationObserver === 'function'
    ? new MutationObserver(scheduleSync)
    : null;
  observer?.observe(document.body, { childList: true, subtree: true });
  scheduleSync();

  return () => {
    observer?.disconnect();
    window.removeEventListener(LIFECYCLE_EVENT, scheduleSync);
    window.removeEventListener('pageshow', scheduleSync);
    document.getElementById(ROOT_ID)?.remove();
  };
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') install();
