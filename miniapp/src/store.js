const KEY = 'korgan-miniapp-state-v1';

const emptyState = {
  draft: { documentType: null, description: '' },
  recentCases: [],
};

export function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...emptyState, ...JSON.parse(raw) } : emptyState;
  } catch {
    return emptyState;
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

export function addRecentCase(item) {
  const state = loadState();
  const recentCases = [item, ...state.recentCases.filter(x => x.id !== item.id)].slice(0, 20);
  return saveState({ ...state, recentCases });
}
