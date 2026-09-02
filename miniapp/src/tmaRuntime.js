/*
 * Telegram Mini App runtime bridge adapted from the MIT-licensed tma-shop
 * runtime patterns (SDK initialization, theme/viewport binding and native
 * BackButton/MainButton lifecycle). KORGAN keeps its existing legal and
 * payment domains untouched; this module only owns Telegram client chrome.
 */

const DESKTOP_PLATFORMS = new Set(['tdesktop', 'macos', 'weba', 'webk', 'unigram']);
const MOBILE_PLATFORMS = new Set(['android', 'android_x', 'ios']);

function defaultWindow() {
  return typeof window === 'undefined' ? null : window;
}

function defaultDocument() {
  return typeof document === 'undefined' ? null : document;
}

function defaultMutationObserver() {
  return typeof MutationObserver === 'undefined' ? null : MutationObserver;
}

function themeCssName(key) {
  return `--tg-theme-${String(key || '').replaceAll('_', '-')}`;
}

function setCssProperty(style, name, value) {
  if (!style || typeof style.setProperty !== 'function') return;
  if (value === null || value === undefined || value === '') return;
  style.setProperty(name, String(value));
}

function isDesktopTelegram(tg, win) {
  const platform = String(tg?.platform || '').toLowerCase();
  if (DESKTOP_PLATFORMS.has(platform)) return true;
  if (MOBILE_PLATFORMS.has(platform)) return false;
  return Boolean(win?.matchMedia?.('(min-width: 900px)').matches);
}

function requestDesktopFullscreen(tg, win) {
  if (!isDesktopTelegram(tg, win)) return;
  if (typeof tg?.requestFullscreen !== 'function') return;
  try {
    tg.requestFullscreen();
  } catch {
    // Fullscreen is progressive enhancement. The responsive layout remains the
    // fallback when an older Telegram Desktop client rejects the call.
  }
}

function offTelegramEvent(tg, name, handler) {
  try {
    tg?.offEvent?.(name, handler);
  } catch {
    // Older clients can expose onEvent without a matching offEvent.
  }
}

/**
 * Creates one owner for Telegram client-side chrome.
 *
 * The runtime deliberately does not know anything about KORGAN legal services,
 * documents or payments. Its job is equivalent to tma-shop's SDK shell:
 * initialize Telegram, bind theme/viewport CSS variables and keep the native
 * BackButton/MainButton lifecycle deterministic.
 */
export function createTelegramRuntime({
  getWebApp = () => defaultWindow()?.Telegram?.WebApp ?? null,
  win = defaultWindow(),
  doc = defaultDocument(),
  MutationObserverClass = defaultMutationObserver(),
  backButtonSelector = '.subbar .icon-btn',
  rootSelector = '#root',
} = {}) {
  let tg = null;
  let initialized = false;
  let observer = null;
  let themeHandler = null;
  let viewportHandler = null;
  let backHandler = null;
  let mainHandler = null;
  let domBackTarget = null;
  let fullscreenTimer = null;

  const rootStyle = () => doc?.documentElement?.style ?? null;

  function syncTheme() {
    if (!tg) return;
    const params = tg.themeParams || {};
    const style = rootStyle();
    for (const [key, value] of Object.entries(params)) {
      setCssProperty(style, themeCssName(key), value);
    }
    const scheme = String(tg.colorScheme || '').toLowerCase();
    if (doc?.documentElement?.dataset) {
      doc.documentElement.dataset.tgColorScheme = scheme === 'light' ? 'light' : 'dark';
    }
  }

  function syncInsets(prefix, inset) {
    if (!inset || typeof inset !== 'object') return;
    const style = rootStyle();
    for (const side of ['top', 'right', 'bottom', 'left']) {
      const value = Number(inset[side]);
      if (Number.isFinite(value)) setCssProperty(style, `--tg-${prefix}-${side}`, `${value}px`);
    }
  }

  function syncViewport() {
    if (!tg) return;
    const style = rootStyle();
    const height = Number(tg.viewportHeight);
    const stableHeight = Number(tg.viewportStableHeight);
    if (Number.isFinite(height) && height > 0) setCssProperty(style, '--tg-viewport-height', `${height}px`);
    if (Number.isFinite(stableHeight) && stableHeight > 0) setCssProperty(style, '--tg-viewport-stable-height', `${stableHeight}px`);
    syncInsets('safe-area-inset', tg.safeAreaInset);
    syncInsets('content-safe-area-inset', tg.contentSafeAreaInset);
  }

  function detachBackHandler() {
    if (!tg?.BackButton || !backHandler) return;
    try { tg.BackButton.offClick?.(backHandler); } catch {}
    backHandler = null;
  }

  function hideBackButton() {
    domBackTarget = null;
    detachBackHandler();
    try { tg?.BackButton?.hide?.(); } catch {}
  }

  function showBackButton(onClick) {
    if (!tg?.BackButton || typeof onClick !== 'function') {
      hideBackButton();
      return;
    }
    detachBackHandler();
    backHandler = onClick;
    try {
      tg.BackButton.onClick?.(backHandler);
      tg.BackButton.show?.();
    } catch {
      backHandler = null;
    }
  }

  function syncDomBackButton() {
    if (!doc?.querySelector) return;
    const target = doc.querySelector(backButtonSelector);
    if (!target || typeof target.click !== 'function') {
      if (domBackTarget !== null) hideBackButton();
      return;
    }
    if (target === domBackTarget && backHandler) return;
    domBackTarget = target;
    showBackButton(() => {
      const current = doc.querySelector?.(backButtonSelector);
      if (current && typeof current.click === 'function') current.click();
    });
  }

  function startBackButtonBridge() {
    syncDomBackButton();
    if (!MutationObserverClass || !doc?.querySelector) return;
    const root = doc.querySelector(rootSelector);
    if (!root) return;
    observer = new MutationObserverClass(syncDomBackButton);
    observer.observe(root, { childList: true, subtree: true });
  }

  function detachMainHandler() {
    if (!tg?.MainButton || !mainHandler) return;
    try { tg.MainButton.offClick?.(mainHandler); } catch {}
    mainHandler = null;
  }

  function hideMainButton() {
    detachMainHandler();
    try {
      tg?.MainButton?.hideProgress?.();
      tg?.MainButton?.hide?.();
    } catch {}
  }

  function configureMainButton({
    text = '',
    visible = true,
    enabled = true,
    loading = false,
    onClick = null,
  } = {}) {
    if (!tg?.MainButton) return false;
    detachMainHandler();
    try {
      if (text) tg.MainButton.setText?.(String(text));
      if (enabled && !loading) tg.MainButton.enable?.();
      else tg.MainButton.disable?.();
      if (loading) tg.MainButton.showProgress?.(false);
      else tg.MainButton.hideProgress?.();
      if (visible) tg.MainButton.show?.();
      else tg.MainButton.hide?.();
      if (visible && typeof onClick === 'function') {
        mainHandler = onClick;
        tg.MainButton.onClick?.(mainHandler);
      }
      return true;
    } catch {
      mainHandler = null;
      return false;
    }
  }

  function init() {
    const next = getWebApp?.() ?? null;
    if (!next) return null;
    if (initialized && tg === next) {
      syncTheme();
      syncViewport();
      syncDomBackButton();
      return tg;
    }

    dispose();
    tg = next;
    initialized = true;

    try { tg.ready?.(); } catch {}
    try { tg.expand?.(); } catch {}

    // Preserve KORGAN visual identity instead of importing tma-shop styling.
    try { tg.setHeaderColor?.('#090b0d'); } catch {}
    try { tg.setBackgroundColor?.('#090b0d'); } catch {}
    try { tg.setBottomBarColor?.('#090b0d'); } catch {}

    syncTheme();
    syncViewport();

    themeHandler = () => syncTheme();
    viewportHandler = () => syncViewport();
    try { tg.onEvent?.('themeChanged', themeHandler); } catch {}
    try { tg.onEvent?.('viewportChanged', viewportHandler); } catch {}
    try { tg.onEvent?.('safeAreaChanged', viewportHandler); } catch {}
    try { tg.onEvent?.('contentSafeAreaChanged', viewportHandler); } catch {}

    startBackButtonBridge();

    if (win?.setTimeout) {
      fullscreenTimer = win.setTimeout(() => requestDesktopFullscreen(tg, win), 80);
    } else {
      requestDesktopFullscreen(tg, win);
    }
    return tg;
  }

  function dispose() {
    if (fullscreenTimer !== null && win?.clearTimeout) {
      try { win.clearTimeout(fullscreenTimer); } catch {}
    }
    fullscreenTimer = null;
    observer?.disconnect?.();
    observer = null;
    hideBackButton();
    hideMainButton();
    if (tg && themeHandler) offTelegramEvent(tg, 'themeChanged', themeHandler);
    if (tg && viewportHandler) {
      offTelegramEvent(tg, 'viewportChanged', viewportHandler);
      offTelegramEvent(tg, 'safeAreaChanged', viewportHandler);
      offTelegramEvent(tg, 'contentSafeAreaChanged', viewportHandler);
    }
    themeHandler = null;
    viewportHandler = null;
    domBackTarget = null;
    initialized = false;
    tg = null;
  }

  return {
    init,
    dispose,
    syncTheme,
    syncViewport,
    syncDomBackButton,
    showBackButton,
    hideBackButton,
    configureMainButton,
    hideMainButton,
    get webApp() { return tg; },
  };
}
