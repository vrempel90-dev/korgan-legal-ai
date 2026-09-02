import { korganApi } from './korganApi.js';
import { openSignedDocument } from './documentDelivery.js';
import { loadState } from './store.js';

export const READY_DOCUMENT_ACK_KEY = 'korgan-miniapp-ready-document-opened-v1';

const COPY = {
  ru: {
    title: 'Документ готов',
    action: 'Открыть документ',
    opening: 'Открываю документ…',
    failed: 'Не удалось открыть. Нажмите ещё раз.',
  },
  kk: {
    title: 'Құжат дайын',
    action: 'Құжатты ашу',
    opening: 'Құжат ашылуда…',
    failed: 'Ашу мүмкін болмады. Қайта басыңыз.',
  },
};

const pendingCards = new WeakSet();

function language() {
  return loadState().language === 'kk' ? 'kk' : 'ru';
}

function copy() {
  return COPY[language()];
}

function safeRead(storage) {
  if (!storage || typeof storage.getItem !== 'function') return {};
  try {
    const parsed = JSON.parse(storage.getItem(READY_DOCUMENT_ACK_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function safeWrite(storage, value) {
  if (!storage || typeof storage.setItem !== 'function') return;
  try { storage.setItem(READY_DOCUMENT_ACK_KEY, JSON.stringify(value)); } catch { /* storage is optional */ }
}

function acknowledgementKey(caseId, jobId) {
  return `${String(caseId || '').trim()}:${String(jobId || '').trim()}`;
}

export function isReadyDocumentAcknowledged(caseId, jobId, storage = globalThis.localStorage) {
  const key = acknowledgementKey(caseId, jobId);
  if (key === ':') return false;
  return safeRead(storage)[key] === true;
}

export function acknowledgeReadyDocument(caseId, jobId, storage = globalThis.localStorage) {
  const key = acknowledgementKey(caseId, jobId);
  if (key === ':') return false;
  const state = safeRead(storage);
  state[key] = true;
  safeWrite(storage, state);
  return true;
}

/**
 * Открывает именно сохранённый сервером DOCX. Уведомление считается обработанным
 * только после того, как Telegram/browser подтвердил принятие ссылки.
 */
export async function openReadyDocument({
  caseId,
  jobId,
  api = korganApi,
  openDocument = openSignedDocument,
  storage = globalThis.localStorage,
} = {}) {
  const cid = String(caseId || '').trim();
  const jid = String(jobId || '').trim();
  if (!cid || !jid) throw new Error('Не определён готовый документ');

  const access = await api.documentAccess(cid);
  const url = String(access?.download_url || '').trim();
  if (!access?.ok || !/^https:\/\//i.test(url)) throw new Error('Ссылка на документ не получена');

  const opened = await openDocument(url, access.filename || 'KORGAN_document.docx');
  if (opened !== true) throw new Error('Документ не был открыт');

  acknowledgeReadyDocument(cid, jid, storage);
  return { ok: true, caseId: cid, jobId: jid, filename: access.filename || 'KORGAN_document.docx' };
}

function screenTitle() {
  return String(document.querySelector('.subbar > strong')?.textContent || '').trim();
}

function isCasesScreen() {
  const title = screenTitle();
  return title === 'Мои дела' || title === 'Менің істерім';
}

function caseIdFromCard(card) {
  const metadata = String(card.querySelector('small')?.textContent || '').trim();
  const separator = metadata.indexOf(' · ');
  return String(separator >= 0 ? metadata.slice(0, separator) : metadata).trim();
}

function hasAuthoritativeReadyProgress(card) {
  const progress = card.querySelector('[data-korgan-case-progress]');
  return progress?.dataset?.progressKind === 'ready';
}

function noticeHost(card) {
  const progress = card.querySelector('[data-korgan-case-progress]');
  return progress?.parentElement || card;
}

function removeNoticesOutsideCases() {
  if (isCasesScreen()) return;
  for (const node of document.querySelectorAll('[data-korgan-ready-document]')) node.remove();
}

function buildNotice(card, { caseId, jobId }) {
  const c = copy();
  const notice = document.createElement('span');
  notice.className = 'case-ready-document-notice';
  notice.dataset.korganReadyDocument = 'true';
  notice.dataset.caseId = caseId;
  notice.dataset.jobId = jobId;
  notice.innerHTML = `
    <span class="case-ready-document-icon" aria-hidden="true">✓</span>
    <span class="case-ready-document-copy"><strong></strong><small></small></span>
    <span class="case-ready-document-arrow" aria-hidden="true">›</span>`;
  notice.querySelector('strong').textContent = c.title;
  notice.querySelector('small').textContent = c.action;

  const activate = async event => {
    event.preventDefault();
    event.stopPropagation();
    if (notice.dataset.busy === 'true') return;
    notice.dataset.busy = 'true';
    notice.setAttribute('aria-busy', 'true');
    const small = notice.querySelector('small');
    small.textContent = c.opening;
    try {
      await openReadyDocument({ caseId, jobId });
      card.dataset.korganReadyHandled = jobId;
      notice.remove();
    } catch {
      notice.dataset.busy = 'false';
      notice.removeAttribute('aria-busy');
      small.textContent = c.failed;
      window.setTimeout(() => {
        if (notice.isConnected && notice.dataset.busy !== 'true') small.textContent = c.action;
      }, 3200);
    }
  };

  notice.addEventListener('click', activate);
  return notice;
}

async function resolveReadyCard(card) {
  if (!isCasesScreen() || !card.isConnected || !hasAuthoritativeReadyProgress(card)) return;
  if (card.querySelector('[data-korgan-ready-document]') || pendingCards.has(card)) return;

  const caseId = caseIdFromCard(card);
  if (!caseId) return;
  pendingCards.add(card);
  try {
    const result = await korganApi.caseGeneration(caseId);
    if (!isCasesScreen() || !card.isConnected || !hasAuthoritativeReadyProgress(card)) return;
    const job = result?.job;
    const documentInfo = result?.document;
    const jobId = String(job?.job_id || '').trim();
    const actuallyReady = job?.status === 'succeeded'
      && job?.document_ready === true
      && jobId
      && String(documentInfo?.filename || '').trim();
    if (!actuallyReady) return;

    if (isReadyDocumentAcknowledged(caseId, jobId)) {
      card.dataset.korganReadyHandled = jobId;
      return;
    }
    if (card.dataset.korganReadyHandled === jobId) return;

    noticeHost(card).append(buildNotice(card, { caseId, jobId }));
  } catch {
    // Progress polling remains authoritative. A transient request failure must
    // not create an error toast or move anything to another screen.
  } finally {
    pendingCards.delete(card);
  }
}

function syncReadyNotices() {
  removeNoticesOutsideCases();
  if (!isCasesScreen()) return;
  for (const card of document.querySelectorAll('.subbar + .page .case-list-item')) {
    if (hasAuthoritativeReadyProgress(card)) void resolveReadyCard(card);
    else card.querySelector('[data-korgan-ready-document]')?.remove();
  }
}

export function installReadyDocumentNotices() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return () => {};
  let active = true;
  const run = () => { if (active) syncReadyNotices(); };
  run();
  const timer = window.setInterval(run, 500);
  return () => {
    active = false;
    window.clearInterval(timer);
    for (const node of document.querySelectorAll('[data-korgan-ready-document]')) node.remove();
  };
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') installReadyDocumentNotices();
