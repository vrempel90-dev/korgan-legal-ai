import {
  createLifecycleNotificationLedger,
  generationEvent,
} from './lifecycleNotifications.js';
import { playLifecycleFeedback, unlockLifecycleAudio } from './lifecycleFeedback.js';
import { isSoundEnabled, isVibrationEnabled } from './feedbackPreferences.js';

const EVENT = 'korgan:generation-lifecycle';

export function installLifecycleBridge({ target = globalThis.window, storage = globalThis.localStorage } = {}) {
  if (!target || typeof target.addEventListener !== 'function') return () => {};
  const ledger = createLifecycleNotificationLedger({ storage });
  let audioUnlocked = false;

  const unlock = () => {
    if (audioUnlocked || !isSoundEnabled(storage)) return;
    void unlockLifecycleAudio().then(ok => { audioUnlocked = ok; });
  };

  const listener = event => {
    const detail = event?.detail || {};
    const job = detail.job;
    const eventType = generationEvent(job, detail.document);
    if (!eventType) return;
    const claimed = ledger.claim({ caseId: job.caseId, jobId: job.jobId, eventType });
    if (!claimed) return;
    void playLifecycleFeedback(eventType, {
      soundEnabled: isSoundEnabled(storage),
      vibrationEnabled: isVibrationEnabled(storage),
    });
  };

  target.addEventListener('pointerdown', unlock, { passive: true });
  target.addEventListener('keydown', unlock, { passive: true });
  target.addEventListener(EVENT, listener);
  return () => {
    target.removeEventListener('pointerdown', unlock);
    target.removeEventListener('keydown', unlock);
    target.removeEventListener(EVENT, listener);
  };
}

installLifecycleBridge();
