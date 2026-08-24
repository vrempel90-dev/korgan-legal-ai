const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

async function request(path, options = {}) {
  if (!API_BASE) throw new Error('KORGAN_API_NOT_CONNECTED');

  const tg = window.Telegram?.WebApp;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload?.message || `KORGAN_API_${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const korganApi = {
  health: () => request('/miniapp/health'),
  bootstrap: () => request('/miniapp/bootstrap'),
  consultation: (message, caseId, language = 'ru') => request('/miniapp/consultation', {
    method: 'POST',
    body: JSON.stringify({ message, case_id: caseId || null, language }),
  }),
  createCase: (payload) => request('/miniapp/cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  generateDocument: (payload) => request('/miniapp/documents/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  listCases: () => request('/miniapp/cases'),
  deleteCase: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' }),
  deleteMyData: () => request('/miniapp/me/data', { method: 'DELETE' }),
  acceptConsent: (version, language) => request('/miniapp/consent', {
    method: 'POST',
    body: JSON.stringify({ version, language }),
  }),
};

export const isBackendConnected = () => Boolean(API_BASE);
