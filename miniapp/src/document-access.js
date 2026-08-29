const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

function initData() {
  return window.Telegram?.WebApp?.initData || window.__KORGAN_TG_INIT_DATA__ || '';
}

async function request(path, options = {}) {
  if (!API_BASE) throw new Error('KORGAN_API_NOT_CONNECTED');
  const headers = { ...(options.headers || {}) };
  const auth = initData();
  if (auth) headers['X-Telegram-Init-Data'] = auth;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, cache: 'no-store' });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '');
  if (!response.ok) {
    const detail = typeof payload === 'object' ? (payload?.detail || payload?.message) : payload;
    const error = new Error(detail || `KORGAN_API_${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export function createDocumentAccess(caseId) {
  return request(`/miniapp/cases/${encodeURIComponent(caseId)}/document/access`, { method: 'POST' });
}

export function sendDocumentToTelegram(caseId) {
  return request(`/miniapp/cases/${encodeURIComponent(caseId)}/document/telegram`, { method: 'POST' });
}
