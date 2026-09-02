import './generation-stage-timeline.css';

const ROOT_ID = 'korgan-generation-stage-timeline';

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

function clampProgress(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(numeric, 100));
}

export function stageIndexForProgress(value) {
  const progress = clampProgress(value);
  if (progress >= 100) return 4;
  if (progress >= 90) return 3;
  if (progress >= 80) return 2;
  if (progress >= 20) return 1;
  return 0;
}

export function timelineSignature({ language = 'ru', progress = 0, failed = false } = {}) {
  return `${language}|${clampProgress(progress)}|${failed ? 'failed' : 'running'}`;
}

export function isTimelineOwnedMutation(mutation, root) {
  if (!mutation || !root) return false;
  if (mutation.target === root || root.contains?.(mutation.target)) return true;

  const nodes = [
    ...Array.from(mutation.addedNodes || []),
    ...Array.from(mutation.removedNodes || []),
  ];
  return nodes.length > 0 && nodes.every(node => node === root || root.contains?.(node));
}

function languageFor(page, progress) {
  const text = `${page?.textContent || ''} ${progress?.getAttribute('aria-label') || ''}`;
  return /Құжат|Қазақстан|Дайындық|тексерілуде/.test(text) ? 'kk' : 'ru';
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
  if (!root) {
    root = document.createElement('section');
    root.id = ROOT_ID;
    root.className = 'korgan-generation-stage-timeline';
    progress.insertAdjacentElement('afterend', root);
  }

  root.style.setProperty('--generation-progress', `${value}%`);
  root.style.setProperty('--generation-line-progress', `${Math.min(value * 0.8, 80)}%`);
  root.dataset.progress = String(value);

  // MutationObserver watches the page. Rewriting innerHTML on every observer
  // callback creates a self-sustaining repaint loop. Only touch the subtree when
  // the actual backend state changed.
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

  if (!page || !progress) {
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

  const observer = new MutationObserver(mutations => {
    const root = document.getElementById(ROOT_ID);
    if (root && mutations.length > 0 && mutations.every(mutation => isTimelineOwnedMutation(mutation, root))) return;
    scheduleSync();
  });

  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['aria-valuenow', 'aria-label'],
  });
  window.addEventListener('pageshow', scheduleSync);
  scheduleSync();
}

if (typeof document !== 'undefined' && typeof window !== 'undefined' && typeof MutationObserver !== 'undefined') {
  install();
}
