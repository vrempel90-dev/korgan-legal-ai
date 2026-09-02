const TONES = {
  queued: [520, 0.045],
  running: [620, 0.045],
  ready: [880, 0.08],
  failed: [220, 0.09],
};

function telegramFeedback(eventType, telegram = globalThis.window?.Telegram?.WebApp) {
  const haptic = telegram?.HapticFeedback;
  if (!haptic) return;
  try {
    if (eventType === 'ready') haptic.notificationOccurred?.('success');
    else if (eventType === 'failed') haptic.notificationOccurred?.('error');
    else haptic.impactOccurred?.('light');
  } catch { /* haptics are best-effort */ }
}

/**
 * Короткий синтезированный сигнал без внешних аудиофайлов. Браузер может
 * запретить звук до первого пользовательского жеста — это нормальный Telegram
 * WebView fallback, haptic при этом остаётся доступным.
 */
export async function playLifecycleFeedback(eventType, {
  telegram = globalThis.window?.Telegram?.WebApp,
  AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext,
} = {}) {
  telegramFeedback(eventType, telegram);
  const tone = TONES[eventType];
  if (!tone || typeof AudioContextClass !== 'function') return { sounded: false };

  let context;
  try {
    context = new AudioContextClass();
    if (context.state === 'suspended' && typeof context.resume === 'function') await context.resume();
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
    oscillator.addEventListener?.('ended', () => { context.close?.().catch?.(() => {}); }, { once: true });
    return { sounded: true };
  } catch {
    try { await context?.close?.(); } catch {}
    return { sounded: false };
  }
}
