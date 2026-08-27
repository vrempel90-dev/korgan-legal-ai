const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

async function request(path, options = {}) {
  if (!API_BASE) throw new Error('KORGAN_API_NOT_CONNECTED');
  const tg = window.Telegram?.WebApp;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
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

function requireParity(health, parity) {
  if (
    health?.status !== 'ok'
    || health?.legal_runtime !== 'strict_bot'
    || health?.word_quality_target !== '10/10'
    || parity?.status !== 'ok'
    || parity?.api_version !== '1.1.0'
    || parity?.service_outer !== 'ClaimPipelineV2Adapter'
    || parity?.service_claim_mux !== 'ClaimServiceMux'
    || parity?.service_stable !== 'PretrialResponseProductionService'
    || parity?.word_quality_target !== '10/10'
    || parity?.consultation_ai_receipt_verification !== false
    || parity?.consultation_ofd_receipt_verification !== true
    || parity?.document_manual_confirmation !== false
    || parity?.document_ai_receipt_verification !== false
    || parity?.document_ofd_receipt_verification !== true
    || parity?.receipt_input !== 'fiscal_qr_url'
  ) throw new Error('KORGAN professional Mini App runtime is not ready');
  return { ...health, parity };
}

function requireDocument(payload) {
  if (!payload?.document_base64 || !['verified', 'preliminary'].includes(payload?.release_status)) {
    throw new Error('KORGAN document release metadata is incomplete');
  }
  return payload;
}

async function upload(path, file) {
  const body = new FormData();
  body.append('file', file);
  return request(path, { method: 'POST', body });
}

function normalizeFiscalUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== 'https:' || parsed.hostname !== 'receipt.kaspi.kz') return '';
    return parsed.toString();
  } catch {
    return '';
  }
}

async function detectFiscalQrFromImage(file) {
  if (!file || !String(file.type || '').startsWith('image/')) return '';
  if (typeof window.BarcodeDetector !== 'function') return '';
  try {
    const formats = await window.BarcodeDetector.getSupportedFormats?.().catch(() => []);
    if (Array.isArray(formats) && formats.length && !formats.includes('qr_code')) return '';
    const detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    const bitmap = await createImageBitmap(file);
    try {
      const codes = await detector.detect(bitmap);
      for (const code of codes || []) {
        const url = normalizeFiscalUrl(code?.rawValue);
        if (url) return url;
      }
    } finally {
      bitmap.close?.();
    }
  } catch {
    return '';
  }
  return '';
}

async function resolveFiscalQrUrl(file) {
  const detected = await detectFiscalQrFromImage(file);
  if (detected) return detected;

  const pasted = window.prompt(
    'Не удалось автоматически прочитать QR. Отсканируйте QR именно на фискальном чеке и вставьте сюда открывшуюся ссылку receipt.kaspi.kz',
    '',
  );
  const normalized = normalizeFiscalUrl(pasted);
  if (!normalized) {
    throw new Error('Нужна официальная QR-ссылка фискального чека receipt.kaspi.kz');
  }
  return normalized;
}

async function submitFiscalReceipt(path, file) {
  const qrUrl = await resolveFiscalQrUrl(file);
  return request(path, {
    method: 'POST',
    body: JSON.stringify({ qr_url: qrUrl }),
  });
}

export const korganApi = {
  health: async () => requireParity(
    await request('/health'),
    await request('/miniapp/parity'),
  ),
  pricing: () => request('/miniapp/pricing'),
  acceptConsent: (termsVersion) => request('/miniapp/consent', {
    method: 'POST', body: JSON.stringify({ accepted: true, terms_version: termsVersion }),
  }),
  declineConsent: (termsVersion) => request('/miniapp/consent', {
    method: 'POST', body: JSON.stringify({ accepted: false, terms_version: termsVersion }),
  }),
  listCases: () => request('/miniapp/cases'),
  getCase: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}`),
  createCase: (payload) => request('/miniapp/cases', { method: 'POST', body: JSON.stringify(payload) }),
  deleteCase: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' }),
  deleteMyData: () => request('/miniapp/me', { method: 'DELETE' }),
  uploadMaterial: (caseId, file) => upload(`/miniapp/cases/${encodeURIComponent(caseId)}/materials`, file),
  consultation: (message, caseId, language = 'ru') => request('/miniapp/consultation', {
    method: 'POST', body: JSON.stringify({ message, case_id: caseId || null, language }),
  }),
  pendingConsultationPayment: () => request('/miniapp/consultation/payment/pending'),
  uploadConsultationReceipt: (orderId, file) => submitFiscalReceipt(
    `/miniapp/consultation/payments/${encodeURIComponent(orderId)}/receipt`,
    file,
  ),
  retryPaidConsultation: (orderId) => request(`/miniapp/consultation/payments/${encodeURIComponent(orderId)}/retry`, { method: 'POST' }),
  generateDocument: async (caseId, documentType, language = 'ru') => {
    const result = await request('/miniapp/documents/generate', {
      method: 'POST', body: JSON.stringify({ case_id: caseId, document_type: documentType, language }),
    });
    return result?.payment_required ? result : requireDocument(result);
  },
  uploadDocumentReceipt: async (orderId, file) => requireDocument(
    await submitFiscalReceipt(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/receipt`, file),
  ),
  retryPaidDocument: async (orderId) => requireDocument(
    await request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/retry`, { method: 'POST' }),
  ),
  documentPaymentStatus: (orderId) => request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}`),
  getDocument: async (caseId) => requireDocument(await request(`/miniapp/cases/${encodeURIComponent(caseId)}/document`)),
};

export const isBackendConnected = () => Boolean(API_BASE);