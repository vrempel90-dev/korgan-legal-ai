const KEY = 'korgan-miniapp-state-v1';

const emptyState = {
  language: 'ru',
  consentAccepted: false,
  consentVersion: '2026-08-16-v1',
  draft: { documentType: null, description: '' },
  recentCases: [],
};

export function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...emptyState, ...JSON.parse(raw) } : { ...emptyState };
  } catch {
    return { ...emptyState };
  }
}

export function saveState(next) {
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function saveDraft(patch) {
  const state = loadState();
  return saveState({ ...state, draft: { ...state.draft, ...patch } });
}

export function setLanguage(language) {
  const state = loadState();
  return saveState({ ...state, language: language === 'kk' ? 'kk' : 'ru' });
}

export function acceptConsent(version = emptyState.consentVersion) {
  const state = loadState();
  return saveState({ ...state, consentAccepted: true, consentVersion: version });
}

export function revokeConsent() {
  const state = loadState();
  return saveState({ ...state, consentAccepted: false });
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
  return { ...emptyState };
}
