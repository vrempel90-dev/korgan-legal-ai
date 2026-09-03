export const FEEDBACK_PREFERENCES_KEY = 'korgan-miniapp-feedback-v1';

const DEFAULTS = Object.freeze({
  sound: true,
  vibration: true,
});

function safeStorage(storage = globalThis.localStorage) {
  return storage && typeof storage.getItem === 'function' ? storage : null;
}

export function feedbackPreferences(storage = globalThis.localStorage) {
  const target = safeStorage(storage);
  if (!target) return { ...DEFAULTS };
  try {
    const parsed = JSON.parse(target.getItem(FEEDBACK_PREFERENCES_KEY) || '{}');
    return {
      sound: typeof parsed?.sound === 'boolean' ? parsed.sound : DEFAULTS.sound,
      vibration: typeof parsed?.vibration === 'boolean' ? parsed.vibration : DEFAULTS.vibration,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function setFeedbackPreference(name, enabled, storage = globalThis.localStorage) {
  if (name !== 'sound' && name !== 'vibration') return feedbackPreferences(storage);
  const target = safeStorage(storage);
  const next = { ...feedbackPreferences(storage), [name]: Boolean(enabled) };
  if (target && typeof target.setItem === 'function') {
    try { target.setItem(FEEDBACK_PREFERENCES_KEY, JSON.stringify(next)); } catch { /* local preference is best-effort */ }
  }
  return next;
}

export function isSoundEnabled(storage = globalThis.localStorage) {
  return feedbackPreferences(storage).sound;
}

export function isVibrationEnabled(storage = globalThis.localStorage) {
  return feedbackPreferences(storage).vibration;
}
