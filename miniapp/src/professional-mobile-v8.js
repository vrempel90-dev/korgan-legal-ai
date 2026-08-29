(() => {
  'use strict';

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

  function apply() {
    normalizeDock();
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
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();