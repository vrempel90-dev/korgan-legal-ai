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

function navButtonByText(buttons, patterns) {
  return buttons.find(button => patterns.some(pattern => pattern.test(String(button.textContent || '').trim()))) || null;
}

// Persistent navigation contains only Home / Help / Profile. Cases, document
// preparation and AI-lawyer are intentionally launched from Home and their old
// nav buttons are hidden by CSS. React may therefore mark a hidden button as
// active while a workflow is open, leaving all three visible tabs looking
// inactive. Keep the visible global destination truthful without changing the
// current screen or interrupting the generation job.
function syncVisibleNavigation() {
  const nav = document.querySelector('.bottom-nav');
  if (!nav) return;

  nav.style.setProperty('pointer-events', 'auto', 'important');
  nav.style.setProperty('z-index', '60', 'important');

  const buttons = [...nav.querySelectorAll(':scope > button')];
  if (!buttons.length) return;
  for (const button of buttons) {
    button.style.setProperty('pointer-events', 'auto', 'important');
    button.style.setProperty('touch-action', 'manipulation');
  }

  const title = String(document.querySelector('.subbar > strong')?.textContent || '').trim();
  const help = navButtonByText(buttons, [/^Помощь$/i, /^Көмек$/i]);
  const profile = navButtonByText(buttons, [/^Профиль$/i]);
  const home = navButtonByText(buttons, [/^Главная$/i, /^Басты$/i]) || buttons[0];

  let target = home;
  if (/^(Помощь|Көмек)$/i.test(title)) target = help || home;
  else if (/^Профиль$/i.test(title)) target = profile || home;

  for (const button of buttons) button.classList.toggle('active', button === target);
}

function renderGenerationTimeline() {
  const page = document.querySelector('main.ready-page');
  const progress = page?.querySelector('[role="progressbar"]');
  const root = document.getElementById(ROOT_ID);

  if (!page || !progress) {
    root?.remove();
    return;
  }

  renderTimeline(page, progress);
}

function sync() {
  renderGenerationTimeline();
  syncVisibleNavigation();
}

// Give immediate visual feedback on pointer-down. React still owns navigation;
// this only prevents a valid tap from looking ignored before the next render.
document.addEventListener('pointerdown', event => {
  const button = event.target.closest?.('.bottom-nav > button');
  if (!button) return;
  const nav = button.closest('.bottom-nav');
  for (const item of nav.querySelectorAll(':scope > button')) item.classList.toggle('active', item === button);
}, true);

const observer = new MutationObserver(sync);
observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-valuenow', 'aria-label', 'class'] });
window.addEventListener('pageshow', sync);
window.setInterval(sync, 700);
sync();
