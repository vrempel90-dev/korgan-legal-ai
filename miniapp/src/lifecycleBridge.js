import {
  createLifecycleNotificationLedger,
  generationEvent,
} from './lifecycleNotifications.js';
import { playLifecycleFeedback } from './lifecycleFeedback.js';

const EVENT = 'korgan:generation-lifecycle';

/**
 * Sidecar не рисует DOM и не меняет KORGAN UI. Он только реагирует на реальные
 * backend lifecycle events, которые публикует generationJob, и дедуплицирует
 * haptic/sound по case + job + status.
 */
export function installLifecycleBridge({ target = globalThis.window, storage = globalThis.localStorage } = {}) {
  if (!target || typeof target.addEventListener !== 'function') return () => {};
  const ledger = createLifecycleNotificationLedger({ storage });

  const listener = event => {
    const detail = event?.detail || {};
    const job = detail.job;
    const eventType = generationEvent(job, detail.document);
    if (!eventType) return;
    const claimed = ledger.claim({ caseId: job.caseId, jobId: job.jobId, eventType });
    if (!claimed) return;
    void playLifecycleFeedback(eventType);
  };

  target.addEventListener(EVENT, listener);
  return () => target.removeEventListener(EVENT, listener);
}

installLifecycleBridge();
