export function getTelegramWebApp() {
  return window.Telegram?.WebApp ?? null;
}

function requestTelegramFullscreen(tg) {
  if (!tg || tg.isFullscreen) return;
  if (typeof tg.requestFullscreen !== 'function') return;

  try {
    tg.requestFullscreen();
  } catch {
    // Fullscreen is optional and client-dependent. Safe-area handling below
    // remains the fallback when an older Telegram client rejects the request.
  }
}

function insetValue(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.round(number) : 0;
}

function syncTelegramSafeArea(tg) {
  const root = document.documentElement;
  if (!root || !tg) return;

  const safe = tg.safeAreaInset || {};
  const content = tg.contentSafeAreaInset || {};

  // contentSafeAreaInset accounts for Telegram's own top/bottom controls while
  // safeAreaInset accounts for the physical device cut-out/home indicator.
  // Taking the larger value prevents both the native Telegram header and the
  // bottom navigation from covering MiniApp controls without double-counting.
  const top = Math.max(insetValue(safe.top), insetValue(content.top));
  const bottom = Math.max(insetValue(safe.bottom), insetValue(content.bottom));

  root.style.setProperty('--korgan-telegram-safe-top', `${top}px`);
  root.style.setProperty('--korgan-telegram-safe-bottom', `${bottom}px`);
  root.classList.add('telegram-webapp');
}

function installTelegramSafeAreaSync(tg) {
  if (!tg) return;

  const sync = () => syncTelegramSafeArea(tg);
  sync();

  for (const eventName of [
    'safeAreaChanged',
    'contentSafeAreaChanged',
    'viewportChanged',
    'fullscreenChanged',
  ]) {
    try {
      tg.onEvent?.(eventName, sync);
    } catch {
      // Older clients may not expose newer safe-area/fullscreen events. CSS
      // fallbacks still protect the layout in those clients.
    }
  }

  window.addEventListener('resize', sync, { passive: true });
  window.addEventListener('orientationchange', sync, { passive: true });
}

export function initTelegram() {
  const tg = getTelegramWebApp();
  if (!tg) return null;

  tg.ready();
  tg.expand();
  installTelegramSafeAreaSync(tg);

  // Keep Telegram chrome visually consistent with the KORGAN Mini App. In
  // fullscreen Telegram makes its header transparent and uses this color to
  // choose contrasting system controls.
  tg.setHeaderColor?.('#090b0d');
  tg.setBackgroundColor?.('#090b0d');
  tg.setBottomBarColor?.('#090b0d');

  // Fullscreen is supported by modern Telegram Mini Apps on mobile and desktop.
  // If the client rejects it, the app simply stays expanded with safe areas.
  window.setTimeout(() => requestTelegramFullscreen(tg), 80);

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
