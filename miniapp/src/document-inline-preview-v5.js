let scheduled = false;

function ping(stage, detail = '') {
  try { window.__KORGAN_BOOT_PING__?.(`download-only-v5-${stage}`, String(detail || '')); } catch {}
}

function isKazakh() {
  try {
    const raw = localStorage.getItem('korgan-miniapp-state-v1');
    const state = raw ? JSON.parse(raw) : null;
    return document.documentElement.lang === 'kk' || state?.language === 'kk';
  } catch {
    return document.documentElement.lang === 'kk';
  }
}

function ensureStyles() {
  if (document.getElementById('korgan-download-only-v5-style')) return;
  const style = document.createElement('style');
  style.id = 'korgan-download-only-v5-style';
  style.textContent = `
    .ready-page .document-preview{display:none!important}
    .korgan-open-document-v5{display:none!important}
  `;
  document.head.append(style);
}

function normalizeDownloadButtons() {
  const label = isKazakh() ? 'Құжатты жүктеу' : 'Скачать документ';
  document.querySelectorAll('button').forEach((button) => {
    const text = String(button.textContent || '').trim();
    if (!/скачать\s*(готовый\s*)?(?:документ|docx)|docx\s*жүктеу|дайын\s*docx\s*жүктеу|құжат.*жүктеу/i.test(text)) return;

    const span = button.querySelector('span');
    if (span) span.textContent = label;
    else {
      const textNodes = Array.from(button.childNodes).filter(node => node.nodeType === Node.TEXT_NODE);
      if (textNodes.length) {
        textNodes.forEach((node, index) => { node.textContent = index === textNodes.length - 1 ? ` ${label}` : ''; });
      } else {
        button.append(document.createTextNode(` ${label}`));
      }
    }
    button.setAttribute('aria-label', label);
  });
}

function removePreviewArtifacts() {
  document.querySelectorAll('.korgan-document-viewer-v3').forEach(node => node.remove());
  document.querySelectorAll('.korgan-open-document-v5').forEach(node => node.remove());
  document.documentElement.style.removeProperty('overflow');
}

function apply() {
  ensureStyles();
  removePreviewArtifacts();
  normalizeDownloadButtons();
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    apply();
  });
}

const observer = new MutationObserver(schedule);
function start() {
  apply();
  observer.observe(document.getElementById('root') || document.body, { childList: true, subtree: true, characterData: true });
  ping('installed');
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
