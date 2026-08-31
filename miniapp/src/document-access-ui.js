const API_BASE = String(import.meta.env.VITE_KORGAN_API_BASE || '').replace(/\/$/, '');

const nativeFetch = window.fetch.bind(window);
let activeCaseId = '';

const DOWNLOAD_LABELS = new Set([
  'скачать docx',
  'скачать готовый docx',
  'скачать документ',
  'docx жүктеу',
  'дайын docx жүктеу',
  'құжатты жүктеу',
]);

function normalizedText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase('ru-RU');
}

function rememberCaseId(value) {
  const clean = String(value || '').trim();
  if (clean && clean !== 'undefined' && clean !== 'null') activeCaseId = clean;
}

function captureCaseFromRequest(input, init) {
  try {
    const raw = typeof input === 'string' ? input : input?.url;
    const url = new URL(raw, window.location.origin);
    const match = url.pathname.match(/\/miniapp\/cases\/([^/]+)/);
    if (match) rememberCaseId(decodeURIComponent(match[1]));

    if (url.pathname.endsWith('/miniapp/documents/generate') && init?.body) {
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : null;
      rememberCaseId(body?.case_id);
    }
  } catch (_) {}
}

function captureCaseFromResponse(response) {
  try {
    response.clone().json().then((data) => {
      rememberCaseId(data?.case_id);
      rememberCaseId(data?.case?.id);
      rememberCaseId(data?.payment?.case_id);
    }).catch(() => {});
  } catch (_) {}
}

window.fetch = async function korganTrackedFetch(input, init) {
  captureCaseFromRequest(input, init);
  const response = await nativeFetch(input, init);
  captureCaseFromResponse(response);
  return response;
};

function telegramInitData() {
  return String(
    window.Telegram?.WebApp?.initData ||
    window.__KORGAN_TG_INIT_DATA__ ||
    ''
  );
}

async function fallbackCaseId() {
  if (activeCaseId) return activeCaseId;
  const response = await nativeFetch(`${API_BASE}/miniapp/cases`, {
    headers: { 'X-Telegram-Init-Data': telegramInitData() },
    cache: 'no-store',
  });
  if (!response.ok) throw new Error('Не удалось определить дело документа');
  const data = await response.json();
  const cases = Array.isArray(data?.cases) ? data.cases : [];
  const ready = cases.find((item) => item?.has_document || item?.status === 'document_ready');
  if (!ready?.id) throw new Error('Готовый документ не найден');
  rememberCaseId(ready.id);
  return activeCaseId;
}

async function createDocumentAccess() {
  const caseId = await fallbackCaseId();
  const response = await nativeFetch(
    `${API_BASE}/miniapp/cases/${encodeURIComponent(caseId)}/document/access`,
    {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': telegramInitData() },
      cache: 'no-store',
    },
  );
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok || !data?.preview_url || !data?.download_url) {
    throw new Error(data?.detail || 'Документ временно недоступен');
  }
  return data;
}

function showError(error) {
  const message = String(error?.message || error || 'Не удалось скачать документ');
  try {
    const tg = window.Telegram?.WebApp;
    if (tg && typeof tg.showAlert === 'function') {
      tg.showAlert(message);
      return;
    }
  } catch (_) {}
  window.alert(message);
}

async function openStoredDocument() {
  const access = await createDocumentAccess();
  const tg = window.Telegram?.WebApp;
  if (tg && typeof tg.openLink === 'function') {
    tg.openLink(access.preview_url, { try_instant_view: false });
    return;
  }
  const opened = window.open(access.preview_url, '_blank', 'noopener,noreferrer');
  if (!opened) window.location.assign(access.preview_url);
}

async function downloadStoredDocument() {
  const access = await createDocumentAccess();
  const tg = window.Telegram?.WebApp;
  if (tg && typeof tg.downloadFile === 'function') {
    tg.downloadFile({ url: access.download_url, file_name: access.filename });
    return;
  }
  const link = document.createElement('a');
  link.href = access.download_url;
  link.download = access.filename || 'KORGAN_document.docx';
  link.rel = 'noopener noreferrer';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function isDownloadControl(element) {
  return DOWNLOAD_LABELS.has(normalizedText(element?.textContent));
}

/*
 * Important UX invariant:
 * this adapter must never create, move, restyle or duplicate visible controls.
 * React owns all visible buttons. We only intercept the existing download action
 * so Telegram can use its native file API instead of a blob download.
 */
document.addEventListener('click', (event) => {
  const target = event.target?.closest?.('button, a, [role="button"]');
  if (!target || !isDownloadControl(target)) return;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();

  downloadStoredDocument().catch(showError);
}, true);

window.__KORGAN_DOCUMENT_ACCESS__ = {
  createDocumentAccess,
  openStoredDocument,
  downloadStoredDocument,
};
