import { createDocumentAccess } from './document-access';

const CASE_KEY = 'korgan-last-case-id-v3';
let scheduled = false;

function ping(stage, detail = '') {
  try { window.__KORGAN_BOOT_PING__?.(`inline-preview-v5-${stage}`, String(detail || '')); } catch {}
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

function rememberCaseId(value) {
  const match = String(value || '').match(/KOR-[A-Z0-9]+/i);
  if (!match) return '';
  const caseId = match[0].toUpperCase();
  try { sessionStorage.setItem(CASE_KEY, caseId); } catch {}
  return caseId;
}

function currentCaseId() {
  const direct = rememberCaseId(document.querySelector('[data-case-id]')?.dataset?.caseId || '');
  if (direct) return direct;

  let header = '';
  document.querySelectorAll('.subbar strong').forEach((node) => {
    if (!header) header = rememberCaseId(node.textContent || '');
  });
  if (header) return header;

  try { return rememberCaseId(sessionStorage.getItem(CASE_KEY) || ''); } catch { return ''; }
}

function ensureStyles() {
  if (document.getElementById('korgan-inline-preview-v5-style')) return;
  const style = document.createElement('style');
  style.id = 'korgan-inline-preview-v5-style';
  style.textContent = `
    .ready-page .document-preview.korgan-real-preview-v5{
      display:flex!important;flex-direction:column!important;position:relative!important;
      width:100%!important;height:min(58dvh,680px)!important;min-height:420px!important;
      margin:18px 0 16px!important;padding:0!important;overflow:hidden!important;
      border:1px solid rgba(212,174,43,.2)!important;border-radius:18px!important;
      background:#0c1117!important;box-shadow:0 18px 48px rgba(0,0,0,.32)!important;
    }
    .korgan-preview-v5-toolbar{
      flex:0 0 auto;min-height:46px;display:flex;align-items:center;justify-content:space-between;
      gap:10px;padding:8px 10px 8px 13px;border-bottom:1px solid rgba(255,255,255,.07);
      background:linear-gradient(180deg,#121922,#0e141b);color:#f3f0e9;
    }
    .korgan-preview-v5-toolbar span{min-width:0;display:flex;flex-direction:column;gap:2px}
    .korgan-preview-v5-toolbar strong{font-size:12px;line-height:1.2;letter-spacing:.04em}
    .korgan-preview-v5-toolbar small{font-size:9px;line-height:1.2;color:#8d98a3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:62vw}
    .korgan-preview-v5-open{
      flex:0 0 auto;min-height:32px;padding:0 10px;border-radius:10px;border:1px solid rgba(212,174,43,.24);
      background:rgba(212,174,43,.08);color:#d9b94f;font:700 10px/1 system-ui,-apple-system,sans-serif;
    }
    .korgan-preview-v5-frame{display:block;flex:1 1 auto;width:100%;min-height:0;border:0;background:#fff}
    .korgan-preview-v5-loading,.korgan-preview-v5-error{
      display:grid;place-items:center;flex:1 1 auto;padding:24px;text-align:center;color:#9ba5ae;
      font:500 12px/1.45 system-ui,-apple-system,sans-serif;
    }
    .korgan-preview-v5-error{color:#e0a1a1}
    .korgan-open-document-v5{margin-top:10px!important}
    @media(max-width:420px){
      .ready-page .document-preview.korgan-real-preview-v5{height:55dvh!important;min-height:390px!important;border-radius:15px!important}
      .korgan-preview-v5-toolbar{min-height:44px;padding-left:11px}
      .korgan-preview-v5-toolbar small{max-width:56vw}
    }
  `;
  document.head.append(style);
}

function buildToolbar(container, caseId, filename) {
  const toolbar = document.createElement('div');
  toolbar.className = 'korgan-preview-v5-toolbar';

  const label = document.createElement('span');
  const strong = document.createElement('strong');
  strong.textContent = isKazakh() ? 'Құжатты алдын ала қарау' : 'Предпросмотр документа';
  const small = document.createElement('small');
  small.textContent = filename || caseId;
  label.append(strong, small);

  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'korgan-preview-v5-open korgan-open-document';
  open.textContent = isKazakh() ? 'Толық экран' : 'На весь экран';
  open.setAttribute('aria-label', isKazakh() ? 'Құжатты толық экранда ашу' : 'Открыть документ на весь экран');

  toolbar.append(label, open);
  container.append(toolbar);
}

async function hydrateReadyPreview(container) {
  if (!container || container.dataset.korganPreviewV5State) return;
  const caseId = currentCaseId();
  if (!caseId) {
    ping('case-id-missing');
    return;
  }

  ensureStyles();
  container.dataset.korganPreviewV5State = 'loading';
  container.dataset.caseId = caseId;
  container.classList.add('korgan-real-preview-v5');
  container.replaceChildren();

  buildToolbar(container, caseId, '');
  const loading = document.createElement('div');
  loading.className = 'korgan-preview-v5-loading';
  loading.textContent = isKazakh() ? 'Құжат ашылуда…' : 'Открываю документ…';
  container.append(loading);
  ping('loading', caseId);

  try {
    const access = await createDocumentAccess(caseId);
    if (!access?.preview_url) throw new Error(isKazakh() ? 'Құжат сілтемесі алынбады' : 'Не получена ссылка на предпросмотр');

    const toolbar = container.querySelector('.korgan-preview-v5-toolbar');
    const small = toolbar?.querySelector('small');
    if (small) small.textContent = access.filename || caseId;

    loading.remove();
    const frame = document.createElement('iframe');
    frame.className = 'korgan-preview-v5-frame';
    frame.src = access.preview_url;
    frame.title = access.filename || (isKazakh() ? 'KORGAN құжаты' : 'Документ KORGAN');
    frame.referrerPolicy = 'no-referrer';
    frame.setAttribute('loading', 'eager');
    frame.addEventListener('load', () => {
      container.dataset.korganPreviewV5State = 'ready';
      ping('loaded', caseId);
    }, { once: true });
    container.append(frame);
    ping('opened-inline', caseId);
  } catch (error) {
    container.dataset.korganPreviewV5State = 'error';
    loading.remove();
    const note = document.createElement('div');
    note.className = 'korgan-preview-v5-error';
    note.textContent = error?.message || (isKazakh() ? 'Құжатты ашу мүмкін болмады' : 'Не удалось открыть предпросмотр документа');
    container.append(note);
    ping('error', error?.message || caseId);
  }
}

function ensureOpenButtonForExistingCase() {
  const page = document.querySelector('main.page');
  if (!page || page.classList.contains('ready-page')) return;
  if (page.querySelector('.korgan-open-document-v5')) return;

  const download = Array.from(page.querySelectorAll('button')).find((button) => {
    const text = String(button.textContent || '').trim();
    return /скачать\s*(готовый\s*)?docx|дайын\s*docx\s*жүктеу/i.test(text);
  });
  if (!download) return;

  const caseId = currentCaseId();
  if (!caseId) return;

  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'secondary wide korgan-open-document korgan-open-document-v5';
  open.dataset.caseId = caseId;
  open.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 4.75A1.75 1.75 0 0 1 5.75 3h8.1L20 9.15v10.1A1.75 1.75 0 0 1 18.25 21H5.75A1.75 1.75 0 0 1 4 19.25V4.75Z" stroke="currentColor" stroke-width="1.8"/>
      <path d="M13.5 3v6.5H20M8 14h8M8 17.5h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <span>${isKazakh() ? 'Құжатты ашу' : 'Открыть документ'}</span>`;
  download.insertAdjacentElement('beforebegin', open);
  ping('existing-open-button', caseId);
}

function apply() {
  currentCaseId();
  ensureOpenButtonForExistingCase();
  const preview = document.querySelector('.ready-page .document-preview');
  if (preview) void hydrateReadyPreview(preview);
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    apply();
  });
}

ensureStyles();
const observer = new MutationObserver(schedule);
function start() {
  apply();
  observer.observe(document.getElementById('root') || document.body, { childList: true, subtree: true });
  ping('installed');
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
