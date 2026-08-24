const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

async function request(path, options = {}) {
  if (!API_BASE) {
    throw new Error('KORGAN_API_NOT_CONNECTED');
  }

  const tg = window.Telegram?.WebApp;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) throw new Error(`KORGAN_API_${response.status}`);
  return response.json();
}

export const korganApi = {
  consultation: (message, caseId) => request('/miniapp/consultation', {
    method: 'POST',
    body: JSON.stringify({ message, case_id: caseId || null }),
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
};

export const isBackendConnected = () => Boolean(API_BASE);
