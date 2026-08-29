import { createDocumentAccess, sendDocumentToTelegram } from './document-access';

const CASE_KEY = 'korgan-last-case-id-v3';
const shownNotices = new Map();
let lastCaseId = '';
let scheduled = false;

function ping(stage, detail = '') {
  try { window.__KORGAN_BOOT_PING__?.(`doc-v3-${stage}`, String(detail || '')); } catch {}
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
  lastCaseId = match[0].toUpperCase();
  try { sessionStorage.setItem(CASE_KEY, lastCaseId); } catch {}
  return lastCaseId;
}

function restoreCaseId() {
  try { return rememberCaseId(sessionStorage.getItem(CASE_KEY) || ''); } catch { return ''; }
}

function scanCaseId() {
  const dataNode = document.querySelector('[data-case-id]');
  if (dataNode?.dataset?.caseId) rememberCaseId(dataNode.dataset.caseId);
  document.querySelectorAll('.subbar strong').forEach((node) => rememberCaseId(node.textContent));
  return lastCaseId;
}

function caseIdFrom(element) {
  const dataNode = element?.closest?.('[data-case-id]');
  const fromData = rememberCaseId(dataNode?.dataset?.caseId || '');
  if (fromData) return fromData;
  const shell = element?.closest?.('.app-shell');
  const fromHeader = rememberCaseId(shell?.querySelector?.('.subbar strong')?.textContent || '');
  if (fromHeader) return fromHeader;
  const progress = shell?.querySelector?.('.korgan-document-progress[data-case-id]');
  const fromProgress = rememberCaseId(progress?.dataset?.caseId || '');
  if (fromProgress) return fromProgress;
  return scanCaseId() || restoreCaseId();
}

function toastStack() {
  let stack = document.querySelector('.korgan-polish-toast-stack');
  if (stack) return stack;
  stack = document.createElement('div');
  stack.className = 'korgan-polish-toast-stack';
  stack.setAttribute('aria-live', 'polite');
  document.body.appendChild(stack);
  return stack;
}

function showToast(message, tone = 'success', duration = 3400) {
  if (!message) return;
  const card = document.createElement('div');
  card.className = `korgan-polish-toast ${tone}`;
  const icon = document.createElement('span');
  icon.className = 'korgan-polish-toast-icon';
  icon.textContent = tone === 'error' ? '!' : tone === 'info' ? 'i' : '✓';
  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'korgan-polish-toast-close';
  close.textContent = '×';
  close.setAttribute('aria-label', isKazakh() ? 'Жабу' : 'Закрыть');
  card.append(icon, text, close);
  const dismiss = () => {
    if (!card.isConnected || card.classList.contains('is-leaving')) return;
    card.classList.add('is-leaving');
    window.setTimeout(() => card.remove(), 180);
  };
  close.addEventListener('click', dismiss);
  toastStack().prepend(card);
  window.setTimeout(dismiss, duration);
}

function suppressGlobalStatus() {
  const profilePage = Boolean(document.querySelector('main.page .profile-card'));

  document.querySelectorAll('.connection-banner, .connection-note, .top-status').forEach((node) => {
    const belongsToProfile = Boolean(node.closest('main.page')?.querySelector('.profile-card'));
    if (profilePage && belongsToProfile) {
      node.style.removeProperty('display');
      node.removeAttribute('data-korgan-profile-only-hidden');
    } else {
      node.style.setProperty('display', 'none', 'important');
      node.setAttribute('data-korgan-profile-only-hidden', '1');
    }
  });

  const now = Date.now();
  for (const [key, expiry] of shownNotices) if (expiry <= now) shownNotices.delete(key);

  document.querySelectorAll('.warning-note').forEach((node) => {
    if (node.classList.contains('left-note')) return;
    if (node.closest('.payment-page') || node.closest('.admin-page') || node.closest('.analysis-card.manual-card')) return;
    if (node.closest('main.page')?.querySelector('.profile-card')) return;

    const message = (node.textContent || '').trim();
    node.style.setProperty('display', 'none', 'important');
    if (!message || node.dataset.korganV3Notice === '1') return;
    node.dataset.korganV3Notice = '1';
    if (shownNotices.has(message)) return;
    shownNotices.set(message, now + 30_000);
    const tone = /ошиб|недоступ|failed|қате|error/i.test(message) ? 'error' : 'info';
    showToast(message, tone, tone === 'error' ? 4800 : 3200);
  });
}

function removeViewer() {
  document.querySelector('.korgan-document-viewer-v3')?.remove();
  document.documentElement.style.removeProperty('overflow');
}

function showViewer(url, filename) {
  removeViewer();
  const viewer = document.createElement('section');
  viewer.className = 'korgan-document-viewer-v3';
  Object.assign(viewer.style, {
    position: 'fixed', inset: '0', zIndex: '2147483646', background: '#0B0F14',
    display: 'flex', flexDirection: 'column', paddingTop: 'env(safe-area-inset-top, 0px)'
  });

  const bar = document.createElement('div');
  Object.assign(bar.style, {
    minHeight: '54px', padding: '8px 12px', display: 'flex', alignItems: 'center',
    gap: '10px', borderBottom: '1px solid rgba(212,174,43,.22)', background: '#0B0F14'
  });
  const close = document.createElement('button');
  close.type = 'button';
  close.textContent = '‹';
  close.setAttribute('aria-label', isKazakh() ? 'Жабу' : 'Закрыть');
  Object.assign(close.style, {
    width: '40px', height: '40px', borderRadius: '12px', border: '1px solid rgba(255,255,255,.13)',
    background: 'rgba(255,255,255,.05)', color: '#F3F0E9', fontSize: '30px', lineHeight: '1', cursor: 'pointer'
  });
  const title = document.createElement('div');
  title.innerHTML = `<strong style="display:block;color:#D4AE2B;letter-spacing:.12em;font-size:13px">KORGAN</strong><span style="display:block;color:#9AA3AE;font-size:11px;max-width:70vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>`;
  title.querySelector('span').textContent = filename || (isKazakh() ? 'Құжат' : 'Документ');
  close.addEventListener('click', removeViewer);
  bar.append(close, title);

  const frame = document.createElement('iframe');
  frame.src = url;
  frame.title = filename || 'KORGAN document';
  frame.referrerPolicy = 'no-referrer';
  Object.assign(frame.style, { flex: '1 1 auto', width: '100%', border: '0', background: '#fff' });
  frame.addEventListener('load', () => ping('preview-loaded', lastCaseId));

  viewer.append(bar, frame);
  document.body.appendChild(viewer);
  document.documentElement.style.setProperty('overflow', 'hidden');
  ping('preview-opened', lastCaseId);
}

function directDownload(url) {
  try {
    const frame = document.createElement('iframe');
    frame.hidden = true;
    frame.setAttribute('aria-hidden', 'true');
    frame.src = url;
    document.body.appendChild(frame);
    window.setTimeout(() => frame.remove(), 20_000);
    return true;
  } catch {
    return false;
  }
}

function nativeDownload(access) {
  const tg = window.Telegram?.WebApp;
  if (!tg || typeof tg.downloadFile !== 'function') return Promise.resolve(false);
  return new Promise((resolve) => {
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      resolve(Boolean(value));
    };
    const timer = window.setTimeout(() => finish(false), 1800);
    try {
      tg.downloadFile({ url: access.download_url, file_name: access.filename }, (accepted) => {
        window.clearTimeout(timer);
        finish(accepted);
      });
    } catch {
      window.clearTimeout(timer);
      finish(false);
    }
  });
}

async function openDocument(button, caseId) {
  if (!caseId || button.dataset.korganV3Busy === '1') return;
  button.dataset.korganV3Busy = '1';
  const wasDisabled = button.disabled;
  button.disabled = true;
  ping('open-click', caseId);
  try {
    const access = await createDocumentAccess(caseId);
    ping('access-ok-open', caseId);
    if (!access?.preview_url) throw new Error(isKazakh() ? 'Құжат сілтемесі алынбады' : 'Не получена ссылка на документ');
    showViewer(access.preview_url, access.filename);
  } catch (error) {
    ping('open-error', error?.message || 'unknown');
    showToast(error?.message || (isKazakh() ? 'Құжатты ашу мүмкін болмады' : 'Не удалось открыть документ'), 'error', 5000);
  } finally {
    button.dataset.korganV3Busy = '0';
    button.disabled = wasDisabled;
  }
}

async function downloadDocument(button, caseId) {
  if (!caseId || button.dataset.korganV3Busy === '1') return;
  button.dataset.korganV3Busy = '1';
  const wasDisabled = button.disabled;
  button.disabled = true;
  ping('download-click', caseId);
  try {
    const access = await createDocumentAccess(caseId);
    ping('access-ok-download', caseId);
    if (!access?.download_url) throw new Error(isKazakh() ? 'Жүктеу сілтемесі алынбады' : 'Не получена ссылка на скачивание');

    const accepted = await nativeDownload(access);
    if (accepted) {
      ping('native-download-accepted', caseId);
      showToast(isKazakh() ? 'Жүктеу басталды' : 'Скачивание началось', 'success', 3200);
      return;
    }

    const directStarted = directDownload(access.download_url);
    ping('direct-download', `${caseId}:${directStarted ? 'started' : 'failed'}`);

    try {
      const delivery = await sendDocumentToTelegram(caseId);
      ping('telegram-delivery-ok', caseId);
      showToast(
        delivery?.message || (isKazakh() ? 'DOCX Telegram чатына жіберілді' : 'DOCX отправлен в чат Telegram'),
        'success', 4200
      );
    } catch (deliveryError) {
      ping('telegram-delivery-error', deliveryError?.message || 'unknown');
      if (directStarted) {
        showToast(isKazakh() ? 'DOCX жүктеу басталды' : 'Загрузка DOCX запущена', 'success', 3200);
      } else {
        throw deliveryError;
      }
    }
  } catch (error) {
    ping('download-error', error?.message || 'unknown');
    showToast(error?.message || (isKazakh() ? 'Құжатты жүктеу мүмкін болмады' : 'Не удалось скачать документ'), 'error', 5200);
  } finally {
    button.dataset.korganV3Busy = '0';
    button.disabled = wasDisabled;
  }
}

function isDownloadButton(button) {
  const text = (button?.textContent || '').trim();
  return /скачать\s*(готовый\s*)?docx|docx\s*жүктеу|дайын\s*docx\s*жүктеу|құжат.*жүктеу/i.test(text);
}

function handleClick(event) {
  const target = event.target?.closest?.('button');
  if (!target) return;
  const open = target.classList.contains('korgan-open-document');
  const download = isDownloadButton(target);
  if (!open && !download) return;

  const caseId = caseIdFrom(target);
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();

  if (!caseId) {
    ping('case-id-missing', (target.textContent || '').trim());
    showToast(isKazakh() ? 'Іс нөмірін анықтау мүмкін болмады' : 'Не удалось определить номер дела', 'error', 4800);
    return;
  }
  if (open) openDocument(target, caseId);
  else downloadDocument(target, caseId);
}

document.addEventListener('click', handleClick, { capture: true });

function apply() {
  scanCaseId();
  suppressGlobalStatus();
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    apply();
  });
}

restoreCaseId();
const observer = new MutationObserver(schedule);
function start() {
  apply();
  observer.observe(document.getElementById('root') || document.body, { childList: true, subtree: true, characterData: true });
  ping('started', lastCaseId || 'none');
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
