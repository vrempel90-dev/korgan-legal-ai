let scheduled = false;

function ping(stage, detail = '') {
  try { window.__KORGAN_BOOT_PING__?.(`document-library-v6-${stage}`, String(detail || '')); } catch {}
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
  if (document.getElementById('korgan-document-library-v6-style')) return;
  const style = document.createElement('style');
  style.id = 'korgan-document-library-v6-style';
  style.textContent = `
    .ready-page .document-preview{display:none!important}
    .korgan-document-saved-note-v6{
      display:flex;align-items:center;gap:8px;margin:10px 0 12px;padding:10px 12px;
      border:1px solid rgba(78,208,160,.18);border-radius:13px;
      background:rgba(78,208,160,.065);color:#AFC9BE;font-size:12px;line-height:1.4
    }
    .korgan-document-saved-note-v6 strong{color:#E8EFEA;font-weight:700}
  `;
  document.head.append(style);
}

function isDownloadButton(button) {
  const text = String(button?.textContent || '').trim();
  return /скачать\s*(готовый\s*)?(?:документ|docx)|docx\s*жүктеу|дайын\s*docx\s*жүктеу|құжат.*жүктеу/i.test(text);
}

function normalizeDownloadButton(button) {
  const label = isKazakh() ? 'Құжатты жүктеу' : 'Скачать документ';
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
}

function ensureLibraryActions(downloadButton) {
  const parent = downloadButton?.parentElement;
  if (!parent) return;

  if (!parent.querySelector('.korgan-document-saved-note-v6')) {
    const note = document.createElement('div');
    note.className = 'korgan-document-saved-note-v6';
    note.innerHTML = isKazakh()
      ? '<span>✓</span><span><strong>Құжат «Менің істерім» бөлімінде сақталды.</strong> Оны кейін қайта ашуға немесе жүктеуге болады.</span>'
      : '<span>✓</span><span><strong>Документ сохранён в «Мои дела».</strong> Его можно открыть или скачать позже без повторной генерации.</span>';
    parent.insertBefore(note, downloadButton);
  }

  if (!parent.querySelector('.korgan-open-document-v6')) {
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'secondary wide korgan-open-document korgan-open-document-v6';
    open.textContent = isKazakh() ? 'Құжатты ашу' : 'Открыть документ';
    open.setAttribute('aria-label', open.textContent);
    parent.insertBefore(open, downloadButton);
  }
}

function apply() {
  ensureStyles();
  document.querySelectorAll('button').forEach((button) => {
    if (!isDownloadButton(button)) return;
    normalizeDownloadButton(button);
    ensureLibraryActions(button);
  });
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
