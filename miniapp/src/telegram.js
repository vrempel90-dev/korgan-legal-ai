export function getTelegramWebApp() {
  return window.Telegram?.WebApp ?? null;
}

export function initTelegram() {
  const tg = getTelegramWebApp();
  if (!tg) return null;
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.('#06152f');
  tg.setBackgroundColor?.('#f4f7fb');
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
  getTelegramWebApp()?.HapticFeedback?.impactOccurred?.('light');
}
