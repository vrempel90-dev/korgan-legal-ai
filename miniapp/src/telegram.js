import { createTelegramRuntime } from './tmaRuntime.js';

let runtime = null;

export function getTelegramWebApp() {
  return window.Telegram?.WebApp ?? null;
}

function getRuntime() {
  if (!runtime) {
    runtime = createTelegramRuntime({ getWebApp: getTelegramWebApp });
  }
  return runtime;
}

/**
 * Initializes Telegram client chrome using the tma-shop runtime model while
 * preserving KORGAN's existing UI, legal core and payment implementation.
 */
export function initTelegram() {
  return getRuntime().init();
}

export function disposeTelegram() {
  runtime?.dispose?.();
  runtime = null;
}

export function setTelegramBackButton(onClick) {
  getRuntime().showBackButton(onClick);
}

export function hideTelegramBackButton() {
  runtime?.hideBackButton?.();
}

export function setTelegramMainButton(options) {
  return getRuntime().configureMainButton(options);
}

export function hideTelegramMainButton() {
  runtime?.hideMainButton?.();
}

export function syncTelegramChrome() {
  runtime?.syncTheme?.();
  runtime?.syncViewport?.();
  runtime?.syncDomBackButton?.();
}

export function getTelegramUser() {
  const user = getTelegramWebApp()?.initDataUnsafe?.user;
  if (!user) return null;
  return {
    id: user.id,
    firstName: user.first_name || '',
    lastName: user.last_name || '',
    username: user.username || '',
    languageCode: user.language_code || 'ru',
  };
}

export function haptic(style = 'light') {
  const feedback = getTelegramWebApp()?.HapticFeedback;
  try {
    feedback?.impactOccurred?.(style);
  } catch {
    // Haptics are optional and must never block a legal action.
  }
}

export function notifyTelegram(type = 'success') {
  const feedback = getTelegramWebApp()?.HapticFeedback;
  try {
    feedback?.notificationOccurred?.(type);
  } catch {
    // Older Telegram clients may not support notification haptics.
  }
}
