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

function languageFor(page, progress) {
  const text = `${page?.textContent || ''} ${progress?.getAttribute('aria-label') || ''}`;
  return /Құжат|Қазақстан|Дайындық|тексерілуде/.test(text) ? 'kk' : 'ru';
}

function stageIndex(progress) {
  const value = Math.max(0, Math.min(Number(progress?.getAttribute('aria-valuenow') || 0), 100));
  if (value >= 100) return 4;
  if (value >= 90) return 3;
  if (value >= 80) return 2;
  if (value >= 20) return 1;
  return 0;
}

function renderTimeline(page, progress) {
  if (!page || !progress) return null;
  const lang = languageFor(page, progress);
  const copy = COPY[lang];
  const value = Math.max(0, Math.min(Number(progress.getAttribute('aria-valuenow') || 0), 100));
  const active = stageIndex(progress);
  const failed = /Подготовка не завершилась|Дайындау аяқталмады/.test(page.textContent || '');

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

  root.innerHTML = `
    <div class="korgan-generation-stage-title">
      <strong>${copy.title}</strong>
      <span>${failed ? (lang === 'kk' ? 'Қате' : 'Ошибка') : copy.live}</span>
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

const observer = new MutationObserver(sync);
observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-valuenow', 'aria-label'] });
window.addEventListener('pageshow', sync);
window.setInterval(sync, 700);
sync();
