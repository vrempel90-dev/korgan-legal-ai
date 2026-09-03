const TONES = {
  queued: [520, 0.045],
  running: [620, 0.045],
  ready: [880, 0.08],
  failed: [220, 0.09],
};

let sharedAudioContext = null;
let sharedAudioClass = null;

function telegramFeedback(eventType, telegram = globalThis.window?.Telegram?.WebApp) {
  const haptic = telegram?.HapticFeedback;
  if (!haptic) return;
  try {
    if (eventType === 'ready') haptic.notificationOccurred?.('success');
    else if (eventType === 'failed') haptic.notificationOccurred?.('error');
    else haptic.impactOccurred?.('light');
  } catch { /* haptics are best-effort */ }
}

function audioClass(value) {
  return value || globalThis.AudioContext || globalThis.webkitAudioContext;
}

function getAudioContext(AudioContextClass) {
  const Type = audioClass(AudioContextClass);
  if (typeof Type !== 'function') return null;
  if (!sharedAudioContext || sharedAudioClass !== Type || sharedAudioContext.state === 'closed') {
    sharedAudioContext = new Type();
    sharedAudioClass = Type;
  }
  return sharedAudioContext;
}

export async function unlockLifecycleAudio({ AudioContextClass } = {}) {
  try {
    const context = getAudioContext(AudioContextClass);
    if (!context) return false;
    if (context.state === 'suspended' && typeof context.resume === 'function') await context.resume();
    return context.state !== 'suspended';
  } catch {
    return false;
  }
}

export async function playLifecycleFeedback(eventType, {
  telegram = globalThis.window?.Telegram?.WebApp,
  AudioContextClass,
  soundEnabled = true,
  vibrationEnabled = true,
} = {}) {
  if (vibrationEnabled) telegramFeedback(eventType, telegram);
  const tone = TONES[eventType];
  if (!tone || !soundEnabled) return { sounded: false };

  try {
    const context = getAudioContext(AudioContextClass);
    if (!context) return { sounded: false };
    if (context.state === 'suspended' && typeof context.resume === 'function') await context.resume();
    if (context.state === 'suspended') return { sounded: false };

    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.value = tone[0];
    gain.gain.value = 0.045;
    oscillator.connect(gain);
    gain.connect(context.destination);
    const start = context.currentTime;
    gain.gain.setValueAtTime?.(0.045, start);
    gain.gain.exponentialRampToValueAtTime?.(0.0001, start + tone[1]);
    oscillator.start(start);
    oscillator.stop(start + tone[1]);
    return { sounded: true };
  } catch {
    return { sounded: false };
  }
}
