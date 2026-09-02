import { feedbackPreferences, setFeedbackPreference } from './feedbackPreferences.js';
import { korganApi } from './korganApi.js';
import { clearAllLocalData, loadState } from './store.js';

const COPY = {
  ru: {
    hero: 'Ваш AI-юрист',
    sound: 'Звук уведомлений',
    soundSub: 'Сигнал при изменении статуса подготовки документа',
    vibration: 'Вибрация',
    vibrationSub: 'Виброотклик MiniApp и уведомлений',
    deleteAll: 'Удалить все мои данные',
    confirmDelete: 'Удалить все данные Mini App и все дела?',
    deleting: 'Удаляю данные…',
    deleteFailed: 'Не удалось удалить данные. Повторите попытку.',
    lawyerReview: 'Проверка юристом',
  },
  kk: {
    hero: 'Сіздің AI-заңгеріңіз',
    sound: 'Хабарлама дыбысы',
    soundSub: 'Құжат дайындау мәртебесі өзгергенде дыбыс',
    vibration: 'Діріл',
    vibrationSub: 'MiniApp және хабарламалардың діріл жауабы',
    deleteAll: 'Барлық деректерімді жою',
    confirmDelete: 'Mini App деректерін және барлық істерді жою керек пе?',
    deleting: 'Деректер жойылуда…',
    deleteFailed: 'Деректерді жою мүмкін болмады. Қайталап көріңіз.',
    lawyerReview: 'Заңгер тексеруі',
  },
};

function language() {
  return loadState().language === 'kk' ? 'kk' : 'ru';
}

function text() {
  return COPY[language()];
}

function screenTitle() {
  return String(document.querySelector('.subbar > strong')?.textContent || '').trim();
}

function isProfile() {
  const title = screenTitle();
  return title === 'Профиль';
}

function isCases() {
  const title = screenTitle();
  return title === 'Мои дела' || title === 'Менің істерім';
}

function isDocuments() {
  const title = screenTitle();
  return title === 'Выбор документа' || title === 'Құжатты таңдау';
}

function applyHero() {
  const hero = document.querySelector('.home-page .hero');
  if (!hero) return;
  const heading = hero.querySelector('h1');
  if (heading) heading.textContent = text().hero;
  const startButton = hero.querySelector('.hero-copy > button');
  if (startButton) startButton.hidden = true;
}

function simplifyLawyerReviewCopy() {
  const replacements = new Map([
    ['Проверка живым юристом', COPY.ru.lawyerReview],
    ['Тірі заңгердің тексеруі', COPY.kk.lawyerReview],
  ]);
  for (const button of document.querySelectorAll('button')) {
    const current = String(button.textContent || '').trim();
    if (!replacements.has(current)) continue;
    const label = replacements.get(current);
    const textNode = [...button.childNodes].find(node => node.nodeType === Node.TEXT_NODE && String(node.textContent || '').trim());
    if (textNode) textNode.textContent = label;
  }
}

function toggleRow({ name, label, description, checked }) {
  const row = document.createElement('div');
  row.className = 'feedback-setting-row';
  row.innerHTML = `
    <div class="feedback-setting-copy">
      <strong></strong>
      <small></small>
    </div>
    <label class="feedback-switch">
      <input type="checkbox" data-feedback-preference="${name}">
      <span class="feedback-switch-track"><span class="feedback-switch-thumb"></span></span>
    </label>`;
  row.querySelector('strong').textContent = label;
  row.querySelector('small').textContent = description;
  const input = row.querySelector('input');
  input.checked = checked;
  input.setAttribute('aria-label', label);
  input.addEventListener('change', () => setFeedbackPreference(name, input.checked));
  return row;
}

function cleanupInjectedUi() {
  const profile = isProfile();
  const cases = isCases();
  const documents = isDocuments();

  for (const node of document.querySelectorAll('[data-korgan-feedback-settings]')) {
    if (!profile) node.remove();
  }
  for (const node of document.querySelectorAll('[data-korgan-delete-all]')) {
    const location = node.dataset.korganDeleteAll;
    if ((location === 'cases' && !cases) || (location === 'documents' && !documents) || !['cases', 'documents'].includes(location)) {
      node.remove();
    }
  }

  // React can reuse a DOM button between screens. Never let the profile-only
  // visibility override leak to another screen.
  for (const button of document.querySelectorAll('[data-korgan-native-profile-delete]')) {
    button.hidden = false;
    button.style.removeProperty('display');
    delete button.dataset.korganNativeProfileDelete;
  }
}

function ensureFeedbackSettings() {
  if (!isProfile()) return;
  const page = document.querySelector('.subbar + .page');
  if (!page || page.querySelector('[data-korgan-feedback-settings]')) return;

  const prefs = feedbackPreferences();
  const section = document.createElement('section');
  section.className = 'settings-card feedback-settings-card';
  section.dataset.korganFeedbackSettings = 'true';
  section.append(
    toggleRow({ name: 'sound', label: text().sound, description: text().soundSub, checked: prefs.sound }),
    toggleRow({ name: 'vibration', label: text().vibration, description: text().vibrationSub, checked: prefs.vibration }),
  );

  // Только Профиль и именно внизу его содержимого.
  page.append(section);
}

function hideProfileDelete() {
  if (!isProfile()) return;
  const page = document.querySelector('.subbar + .page');
  if (!page) return;
  for (const button of page.querySelectorAll('button')) {
    const value = String(button.textContent || '').trim();
    if (value !== COPY.ru.deleteAll && value !== COPY.kk.deleteAll) continue;
    button.dataset.korganNativeProfileDelete = 'true';
    button.hidden = true;
    button.style.setProperty('display', 'none', 'important');
  }
}

async function deleteAllFromMiniApp(button) {
  const copy = text();
  if (!window.confirm(copy.confirmDelete)) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = copy.deleting;
  try {
    await korganApi.deleteMyData();
    clearAllLocalData();
    window.location.reload();
  } catch {
    button.disabled = false;
    button.textContent = original;
    window.alert(copy.deleteFailed);
  }
}

function createDeleteButton(location) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary wide danger relocated-delete-all';
  button.dataset.korganDeleteAll = location;
  button.innerHTML = '<span class="delete-data-icon" aria-hidden="true">⌫</span><span></span>';
  button.querySelector('span:last-child').textContent = text().deleteAll;
  button.addEventListener('click', () => deleteAllFromMiniApp(button));
  return button;
}

function ensureDeleteActions() {
  const page = document.querySelector('.subbar + .page');
  if (!page) return;

  if (isCases() && !page.querySelector('[data-korgan-delete-all="cases"]')) {
    page.append(createDeleteButton('cases'));
  }

  if (isDocuments() && !page.querySelector('[data-korgan-delete-all="documents"]')) {
    const button = createDeleteButton('documents');
    const list = page.querySelector('.list-card');
    if (list?.nextSibling) page.insertBefore(button, list.nextSibling);
    else page.append(button);
  }
}

function applyUi() {
  cleanupInjectedUi();
  applyHero();
  simplifyLawyerReviewCopy();
  hideProfileDelete();
  ensureDeleteActions();
  ensureFeedbackSettings();
}

applyUi();
document.addEventListener('click', () => window.setTimeout(applyUi, 0), true);
window.setInterval(applyUi, 500);
