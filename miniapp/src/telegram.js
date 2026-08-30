export function getTelegramWebApp() {
  return window.Telegram?.WebApp ?? null;
}

function isDesktopTelegram(tg) {
  const platform = String(tg?.platform || '').toLowerCase();
  const desktopPlatforms = new Set(['tdesktop', 'macos', 'weba', 'webk', 'unigram']);
  const mobilePlatforms = new Set(['android', 'android_x', 'ios']);

  if (desktopPlatforms.has(platform)) return true;
  if (mobilePlatforms.has(platform)) return false;

  // Fallback for future/unknown Telegram desktop clients.
  return Boolean(window.matchMedia?.('(min-width: 900px)').matches);
}

function requestDesktopFullscreen(tg) {
  if (!isDesktopTelegram(tg)) return;
  if (typeof tg?.requestFullscreen !== 'function') return;

  try {
    tg.requestFullscreen();
  } catch {
    // Older Telegram clients may expose no fullscreen support. The responsive
    // desktop layout remains the safe fallback in that case.
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

  for (const eventName of ['safeAreaChanged', 'contentSafeAreaChanged', 'viewportChanged']) {
    try {
      tg.onEvent?.(eventName, sync);
    } catch {
      // Older clients may not expose newer safe-area events. CSS/viewport
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

  // Keep Telegram chrome visually consistent with the KORGAN Mini App.
  tg.setHeaderColor?.('#090b0d');
  tg.setBackgroundColor?.('#090b0d');
  tg.setBottomBarColor?.('#090b0d');

  // Telegram Desktop normally opens Mini Apps in a narrow WebView. Ask modern
  // desktop clients for fullscreen without changing mobile behaviour.
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
  getTelegramWebApp()?.HapticFeedback?.impactOccurred?.('light');
}
