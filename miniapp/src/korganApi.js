const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';

const LEGACY_UPLOAD_ONLY_DESCRIPTIONS = new Set([
  'Дело создано на основании загруженных материалов. Факты следует брать только из документов, загруженных пользователем.',
  'Іс жүктелген материалдар негізінде құрылды. Фактілерді тек пайдаланушы жүктеген құжаттардан алу керек.',
]);

async function request(path, options = {}) {
  if (!API_BASE) throw new Error('KORGAN_API_NOT_CONNECTED');

  const tg = window.Telegram?.WebApp;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };

  const initData = tg?.initData || window.__KORGAN_TG_INIT_DATA__ || '';
  if (initData) headers['X-Telegram-Init-Data'] = initData;

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

function requireProfessionalRuntime(health, parity) {
  if (
    health?.status !== 'ok'
    || health?.legal_runtime !== 'strict_bot'
    || health?.word_quality_target !== '10/10'
    || health?.preliminary_fallback !== true
    || parity?.status !== 'ok'
    || parity?.api_version !== '1.0.0'
    || parity?.service_outer !== 'ClaimPipelineV2Adapter'
    || parity?.service_claim_mux !== 'ClaimServiceMux'
    || parity?.service_stable !== 'PretrialResponseProductionService'
    || parity?.word_quality_target !== '10/10'
    || parity?.preliminary_fallback !== true
    || typeof parity?.consultation_limit_enabled !== 'boolean'
    || typeof parity?.document_payments_enabled !== 'boolean'
    || (parity?.document_payments_enabled && parity?.document_manual_confirmation !== false)
  ) {
    throw new Error('KORGAN professional legal runtime is not ready');
  }
  return { ...health, parity };
}

function requireProfessionalDocument(payload) {
  if (
    !payload
    || typeof payload.filing_ready !== 'boolean'
    || !['verified', 'preliminary'].includes(payload.release_status)
    || !payload.document_base64
  ) {
    throw new Error('KORGAN document release metadata is incomplete');
  }
  return payload;
}

async function uploadMaterial(caseId, file) {
  const body = new FormData();
  body.append('file', file);
  return request(`/miniapp/cases/${encodeURIComponent(caseId)}/materials`, { method: 'POST', body });
}

async function uploadConsultationReceipt(orderId, file) {
  const body = new FormData();
  body.append('file', file);
  return request(`/miniapp/consultation/payments/${encodeURIComponent(orderId)}/receipt`, { method: 'POST', body });
}

async function uploadDocumentReceipt(orderId, file) {
  const body = new FormData();
  body.append('file', file);
  const result = await request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/receipt`, { method: 'POST', body });
  return result?.document_base64 ? requireProfessionalDocument(result) : result;
}

async function submitConsultationReceiptUrl(orderId, receiptUrl) {
  return request(`/miniapp/consultation/payments/${encodeURIComponent(orderId)}/receipt-url`, {
    method: 'POST',
    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),
  });
}

async function submitDocumentReceiptUrl(orderId, receiptUrl) {
  const result = await request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/receipt-url`, {
    method: 'POST',
    body: JSON.stringify({ receipt_url: String(receiptUrl || '').trim() }),
  });
  return result?.document_base64 ? requireProfessionalDocument(result) : result;
}

export const korganApi = {
  health: async () => {
    const [health, parity] = await Promise.all([
      request('/health'),
      request('/miniapp/parity'),
    ]);
    return requireProfessionalRuntime(health, parity);
  },
  pricing: () => request('/miniapp/pricing'),
  consultation: (message, caseId, language = 'ru') => request('/miniapp/consultation', {
    method: 'POST',
    body: JSON.stringify({ message, case_id: caseId || null, language }),
  }),
  uploadConsultationReceipt,
  submitConsultationReceiptUrl,
  retryPaidConsultation: (orderId) => request(`/miniapp/consultation/payments/${encodeURIComponent(orderId)}/retry`, {
    method: 'POST',
  }),
  createCase: (payload) => {
    const description = String(payload?.description || '').trim();
    const safePayload = {
      ...payload,
      description: LEGACY_UPLOAD_ONLY_DESCRIPTIONS.has(description) ? '' : description,
    };
    return request('/miniapp/cases', {
      method: 'POST',
      body: JSON.stringify(safePayload),
    });
  },
  getCase: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}`),
  sendDocumentToTelegram: (caseId) => request(
    `/miniapp/cases/${encodeURIComponent(caseId)}/document/telegram`,
    { method: 'POST' },
  ),
  getDocument: async (caseId) => requireProfessionalDocument(
    await request(`/miniapp/cases/${encodeURIComponent(caseId)}/document`),
  ),
  uploadMaterial,
  uploadMaterials: async (caseId, files, onProgress) => {
    const list = Array.from(files || []);
    const results = [];
    for (let index = 0; index < list.length; index += 1) {
      const file = list[index];
      const result = await uploadMaterial(caseId, file);
      results.push({ file, result });
      onProgress?.({ current: index + 1, total: list.length, file, result });
    }
    return results;
  },
  generateDocument: async (caseId, documentType = 'claim', language = 'ru') => {
    const result = await request('/miniapp/documents/generate', {
      method: 'POST',
      body: JSON.stringify({ case_id: caseId, document_type: documentType, language }),
    });
    return result?.payment_required ? result : requireProfessionalDocument(result);
  },
  uploadDocumentReceipt,
  submitDocumentReceiptUrl,
  retryPaidDocument: async (orderId) => requireProfessionalDocument(
    await request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/retry`, { method: 'POST' }),
  ),
  documentPaymentStatus: (orderId) => request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}`),
  adminDocumentPayments: (status = 'awaiting_admin') => request(`/miniapp/admin/document-payments?status=${encodeURIComponent(status)}`),
  adminDocumentPaymentDecision: (orderId, approved, note = '') => request(`/miniapp/admin/document-payments/${encodeURIComponent(orderId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ approved: Boolean(approved), note }),
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
