import { clearLifecycleNotificationData } from './lifecycleNotifications.js';

const KEY = 'korgan-miniapp-state-v1';
const READY_DOCUMENT_ACK_KEY = 'korgan-miniapp-ready-document-opened-v1';

const emptyState = {
  language: 'ru',
  draft: { documentType: null, description: '' },
  recentCases: [],
};

function browserState(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ...emptyState };
  return {
    language: value.language === 'kk' ? 'kk' : 'ru',
    draft: {
      documentType: value.draft?.documentType || null,
      description: String(value.draft?.description || ''),
    },
    recentCases: Array.isArray(value.recentCases) ? value.recentCases : [],
  };
}

export function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? browserState(JSON.parse(raw)) : browserState(emptyState);
  } catch {
    return browserState(emptyState);
  }
}

export function saveState(next) {
  const safe = browserState(next);
  localStorage.setItem(KEY, JSON.stringify(safe));
  return safe;
}

export function saveDraft(patch) {
  const state = loadState();
  return saveState({ ...state, draft: { ...state.draft, ...patch } });
}

export function setLanguage(language) {
  const state = loadState();
  return saveState({ ...state, language: language === 'kk' ? 'kk' : 'ru' });
}

export function addRecentCase(item) {
  const state = loadState();
  const recentCases = [item, ...state.recentCases.filter(x => x.id !== item.id)].slice(0, 20);
  return saveState({ ...state, recentCases });
}

export function clearLocalCaseData() {
  const state = loadState();
  return saveState({
    ...state,
    draft: { documentType: null, description: '' },
    recentCases: [],
  });
}

export function clearAllLocalData() {
  localStorage.removeItem(KEY);
  localStorage.removeItem(READY_DOCUMENT_ACK_KEY);
  clearLifecycleNotificationData();
  return browserState(emptyState);
}
