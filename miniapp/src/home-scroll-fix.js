function resetKorganHomeScroll() {
  const home = document.querySelector('.workspace-home');
  if (!home) return;
  home.scrollTop = 0;
  window.scrollTo(0, 0);
}

try {
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
} catch {}

const resetSoon = () => requestAnimationFrame(() => requestAnimationFrame(resetKorganHomeScroll));

window.addEventListener('pageshow', resetSoon);
window.addEventListener('load', resetSoon);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) resetSoon();
});

const root = document.getElementById('root');
if (root) {
  const observer = new MutationObserver(() => {
    const home = document.querySelector('.workspace-home');
    if (!home || home.dataset.scrollReady === '1') return;
    home.dataset.scrollReady = '1';
    resetSoon();
  });
  observer.observe(root, { childList: true, subtree: true });
}
