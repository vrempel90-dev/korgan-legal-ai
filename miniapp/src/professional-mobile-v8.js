(() => {
  'use strict';

  function ensureV10Styles() {
    if (document.querySelector('link[data-korgan-mobile-v10]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/src/professional-mobile-v10.css';
    link.dataset.korganMobileV10 = '1';
    document.head.appendChild(link);
  }

  function normalizeDock() {
    document.querySelectorAll('.bottom-nav').forEach((nav) => {
      const buttons = Array.from(nav.children).filter((node) => node instanceof HTMLButtonElement);
      if (!buttons.length) return;

      // React order: Home, Cases, AI lawyer, Help, Profile.
      // Keep the four primary app destinations in the persistent dock.
      nav.style.setProperty('grid-template-columns', 'repeat(4, minmax(0, 1fr))', 'important');
      buttons.forEach((button, index) => {
        const visible = index === 0 || index === 1 || index === 2 || index === 4;
        button.style.setProperty('display', visible ? 'grid' : 'none', 'important');
        button.setAttribute('aria-hidden', visible ? 'false' : 'true');
        button.tabIndex = visible ? 0 : -1;
      });
    });
  }

  function normalizeHome() {
    const home = document.querySelector('.native-home');
    if (!home) return;

    const hub = home.querySelector('.native-service-hub');
    const grid = home.querySelector('.native-service-grid');
    [hub, grid].filter(Boolean).forEach((node) => {
      node.style.setProperty('max-height', 'none', 'important');
      node.style.setProperty('overflow', 'visible', 'important');
    });
  }

  function apply() {
    ensureV10Styles();
    normalizeDock();
    normalizeHome();
  }

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      apply();
    });
  }

  function start() {
    apply();
    const root = document.getElementById('root') || document.body;
    const observer = new MutationObserver(schedule);
    observer.observe(root, { childList: true, subtree: true });
    window.addEventListener('pageshow', schedule);
    window.addEventListener('resize', schedule, { passive: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();