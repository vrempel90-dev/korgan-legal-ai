import { requireProfessionalDocument, requireProfessionalRuntime } from './runtimeReadiness.js';
import { createApiTransport } from './apiTransport.js';
import { clearLifecycleNotificationCase } from './lifecycleNotifications.js';
import { recoverGenerationStart } from './generationStartRecovery.js';

const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';
const request = createApiTransport({
  baseUrl: API_BASE,
  getTelegramInitData: () => window.Telegram?.WebApp?.initData || '',
});

const LEGACY_UPLOAD_ONLY_DESCRIPTIONS = new Set([
  'Дело создано на основании загруженных материалов. Факты следует брать только из документов, загруженных пользователем.',
  'Іс жүктелген материалдар негізінде құрылды. Фактілерді тек пайдаланушы жүктеген құжаттардан алу керек.',
]);

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
  return request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}/receipt`, { method: 'POST', body });
}

async function generateDocument(caseId, documentType = 'claim', language = 'ru') {
  try {
    // Job creation is a short server operation. If it does not answer quickly,
    // do not tell the user to start again: the paid job may already exist.
    return await request('/miniapp/documents/generate', {
      method: 'POST',
      body: JSON.stringify({ case_id: caseId, document_type: documentType, language }),
      timeoutMs: 8000,
    });
  } catch (error) {
    return recoverGenerationStart({
      caseId,
      error,
      fetchCaseGeneration: (id) => request(
        `/miniapp/cases/${encodeURIComponent(id)}/generation`,
        { timeoutMs: 4000 },
      ),
    });
  }
}

export const korganApi = {
  health: async (options = {}) => {
    const [health, parity] = await Promise.all([
      request('/health', options),
      request('/miniapp/parity', options),
    ]);
    return requireProfessionalRuntime(health, parity);
  },
  consentStatus: (options = {}) => request('/miniapp/consent', options),
  pricing: (options = {}) => request('/miniapp/pricing', options),
  consultation: (message, caseId, language = 'ru') => request('/miniapp/consultation', {
    method: 'POST',
    body: JSON.stringify({ message, case_id: caseId || null, language }),
  }),
  uploadConsultationReceipt,
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
  caseActivity: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}/activity`),
  getDocument: async (caseId) => requireProfessionalDocument(
    await request(`/miniapp/cases/${encodeURIComponent(caseId)}/document`),
  ),
  documentAccess: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}/document/access`, {
    method: 'POST',
  }),
  sendDocumentToTelegram: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}/document/telegram`, {
    method: 'POST',
  }),
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
  // Запуск подготовки отвечает описанием задачи: сам документ готовится на
  // сервере и приходит отдельным опросом состояния. Таймаут запуска не
  // провоцирует второй POST: сначала восстанавливаем уже сохранённую задачу.
  generateDocument,
  generationStatus: (jobId) => request(`/miniapp/documents/generation/${encodeURIComponent(jobId)}`),
  retryGeneration: (jobId) => request(`/miniapp/documents/generation/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  }),
  // Дело переживает закрытие Mini App, а идентификатор задачи — нет.
  caseGeneration: (caseId) => request(`/miniapp/cases/${encodeURIComponent(caseId)}/generation`),
  uploadDocumentReceipt,
  documentPaymentStatus: (orderId) => request(`/miniapp/documents/payments/${encodeURIComponent(orderId)}`),
  adminDocumentPayments: (status = 'awaiting_admin') => request(`/miniapp/admin/document-payments?status=${encodeURIComponent(status)}`),
  adminDocumentPaymentDecision: (orderId, approved, note = '') => request(`/miniapp/admin/document-payments/${encodeURIComponent(orderId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ approved: Boolean(approved), note }),
  }),
  listCases: (options = {}) => request('/miniapp/cases', options),
  deleteCase: async (caseId) => {
    const result = await request(`/miniapp/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' });
    clearLifecycleNotificationCase(caseId);
    return result;
  },
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
