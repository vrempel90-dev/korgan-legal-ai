export const LIFECYCLE_STORAGE_KEY = 'korgan-miniapp-lifecycle-events-v1';
const ALLOWED_EVENTS = new Set(['queued', 'running', 'ready', 'failed']);

function safeRead(storage) {
  if (!storage || typeof storage.getItem !== 'function') return {};
  try {
    const parsed = JSON.parse(storage.getItem(LIFECYCLE_STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function safeWrite(storage, value) {
  if (!storage || typeof storage.setItem !== 'function') return;
  try { storage.setItem(LIFECYCLE_STORAGE_KEY, JSON.stringify(value)); } catch { /* storage is optional */ }
}

function eventKey(caseId, jobId, eventType) {
  return `${String(caseId || '').trim()}:${String(jobId || '').trim()}:${eventType}`;
}

export function clearLifecycleNotificationData(storage = globalThis.localStorage) {
  if (!storage || typeof storage.removeItem !== 'function') return;
  try { storage.removeItem(LIFECYCLE_STORAGE_KEY); } catch { /* storage is optional */ }
}

export function clearLifecycleNotificationCase(caseId, storage = globalThis.localStorage) {
  const prefix = `${String(caseId || '').trim()}:`;
  if (prefix === ':') return;
  const seen = safeRead(storage);
  for (const key of Object.keys(seen)) {
    if (key.startsWith(prefix)) delete seen[key];
  }
  safeWrite(storage, seen);
}

/**
 * Реестр уже показанных lifecycle-событий.
 *
 * Polling может вернуть один статус десятки раз, а reopen — увидеть уже готовую
 * задачу снова. Реестр гарантирует: один case/job/status даёт максимум одно
 * уведомление и один звук на этом устройстве. Серверное состояние при этом не
 * меняется и остаётся единственным источником истины.
 */
export function createLifecycleNotificationLedger({ storage = globalThis.localStorage, now = () => Date.now(), maxEntries = 200 } = {}) {
  const seen = safeRead(storage);

  const compact = () => {
    const entries = Object.entries(seen)
      .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
      .slice(0, Math.max(20, Number(maxEntries) || 200));
    for (const key of Object.keys(seen)) delete seen[key];
    for (const [key, value] of entries) seen[key] = value;
  };

  const claim = ({ caseId, jobId, eventType }) => {
    const type = String(eventType || '').trim();
    const cid = String(caseId || '').trim();
    const jid = String(jobId || '').trim();
    if (!cid || !jid || !ALLOWED_EVENTS.has(type)) return false;
    const key = eventKey(cid, jid, type);
    if (Object.prototype.hasOwnProperty.call(seen, key)) return false;
    seen[key] = Number(now()) || Date.now();
    compact();
    safeWrite(storage, seen);
    return true;
  };

  const clearCase = (caseId) => clearLifecycleNotificationCase(caseId, storage);

  return { claim, clearCase };
}

export function generationEvent(job, document = null) {
  if (!job || typeof job !== 'object') return null;
  if (job.status === 'failed') return 'failed';
  if (job.status === 'queued') return 'queued';
  if (job.status === 'running') return 'running';
  if (job.status === 'succeeded' && document && String(document.filename || '').trim()) return 'ready';
  return null;
}

export function lifecycleNotificationCopy(eventType, language = 'ru') {
  const kk = language === 'kk';
  const copy = kk ? {
    queued: 'Құжат жұмысқа қабылданды',
    running: 'KORGAN құжатты дайындап жатыр',
    ready: 'Құжат дайын',
    failed: 'Құжатты дайындау мүмкін болмады',
  } : {
    queued: 'Документ принят в работу',
    running: 'KORGAN готовит документ',
    ready: 'Документ готов',
    failed: 'Не удалось подготовить документ',
  };
  return copy[eventType] || '';
}
