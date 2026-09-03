import { isVibrationEnabled } from './feedbackPreferences.js';

export function getTelegramWebApp() {
  return window.Telegram?.WebApp ?? null;
}

function isDesktopTelegram(tg) {
  const platform = String(tg?.platform || '').toLowerCase();
  const desktopPlatforms = new Set(['tdesktop', 'macos', 'weba', 'webk', 'unigram']);
  const mobilePlatforms = new Set(['android', 'android_x', 'ios']);

  if (desktopPlatforms.has(platform)) return true;
  if (mobilePlatforms.has(platform)) return false;

  return Boolean(window.matchMedia?.('(min-width: 900px)').matches);
}

function requestDesktopFullscreen(tg) {
  if (!isDesktopTelegram(tg)) return;
  if (typeof tg?.requestFullscreen !== 'function') return;

  try {
    tg.requestFullscreen();
  } catch {
    // Responsive desktop layout remains the safe fallback.
  }
}

export function initTelegram() {
  const tg = getTelegramWebApp();
  if (!tg) return null;

  tg.ready();
  tg.expand();
  tg.setHeaderColor?.('#090b0d');
  tg.setBackgroundColor?.('#090b0d');
  tg.setBottomBarColor?.('#090b0d');
  window.setTimeout(() => requestDesktopFullscreen(tg), 80);

  return tg;
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

export function haptic() {
  if (!isVibrationEnabled()) return;
  getTelegramWebApp()?.HapticFeedback?.impactOccurred?.('light');
}
