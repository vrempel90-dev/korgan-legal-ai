const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

async function request(path, options = {}) {
  if (!API_BASE) throw new Error('KORGAN_API_NOT_CONNECTED');

  const tg = window.Telegram?.WebApp;
  const headers = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };

  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '');

  if (!response.ok) {
    const detail = typeof payload === 'object' ? (payload?.detail || payload?.message) : payload;
    const error = new Error(detail || `KORGAN_API_${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const korganApi = {
  health: () => request('/health'),
  consultation: (message, caseId, language = 'ru') => request('/miniapp/consultation', {
    method: 'POST',
    body: JSON.stringify({ message, case_id: caseId || null, language }),
  }),
  createCase: (payload) => request('/miniapp/cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  generateDocument: (caseId, documentType = 'claim', language = 'ru') => request('/miniapp/documents/generate', {
    method: 'POST',
    body: JSON.stringify({ case_id: caseId, document_type: documentType, language }),
  }),
  listCases: () => request('/miniapp/cases'),
  deleteCase: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' }),
  deleteMyData: () => request('/miniapp/me', { method: 'DELETE' }),
  acceptConsent: (termsVersion) => request('/miniapp/consent', {
    method: 'POST',
    body: JSON.stringify({ accepted: true, terms_version: termsVersion }),
  }),
  declineConsent: (termsVersion) => request('/miniapp/consent', {
    method: 'POST',
    body: JSON.stringify({ accepted: false, terms_version: termsVersion }),
  }),
};

export const isBackendConnected = () => Boolean(API_BASE);
