import { createDocumentAccess } from './document-access';

const CASE_KEY = 'korgan-last-case-id-v3';

function isKazakh() {
  try {
    const raw = localStorage.getItem('korgan-miniapp-state-v1');
    const state = raw ? JSON.parse(raw) : null;
    return document.documentElement.lang === 'kk' || state?.language === 'kk';
  } catch {
    return document.documentElement.lang === 'kk';
  }
}

function ping(stage, detail = '') {
  try { window.__KORGAN_BOOT_PING__?.(`download-v4-${stage}`, String(detail || '')); } catch {}
}

function rememberCaseId(value) {
  const match = String(value || '').match(/KOR-[A-Z0-9]+/i);
  if (!match) return '';
  const caseId = match[0].toUpperCase();
  try { sessionStorage.setItem(CASE_KEY, caseId); } catch {}
  return caseId;
}

function resolveCaseId(button) {
  const direct = rememberCaseId(button?.closest?.('[data-case-id]')?.dataset?.caseId || '');
  if (direct) return direct;

  const shell = button?.closest?.('.app-shell');
  const header = rememberCaseId(shell?.querySelector?.('.subbar strong')?.textContent || '');
  if (header) return header;

  const progress = rememberCaseId(shell?.querySelector?.('.korgan-document-progress[data-case-id]')?.dataset?.caseId || '');
  if (progress) return progress;

  try {
    return rememberCaseId(sessionStorage.getItem(CASE_KEY) || '');
  } catch {
    return '';
  }
}

function isDownloadButton(button) {
  const text = String(button?.textContent || '').trim();
  return /скачать\s*(готовый\s*)?(?:документ|docx)|docx\s*жүктеу|дайын\s*docx\s*жүктеу|құжат.*жүктеу/i.test(text);
}

function notify(message, error = false) {
  try {
    const old = document.querySelector('.korgan-download-v4-toast');
    old?.remove();
    const toast = document.createElement('div');
    toast.className = 'korgan-download-v4-toast';
    toast.textContent = message;
    Object.assign(toast.style, {
      position: 'fixed',
      left: '50%',
      bottom: 'calc(82px + env(safe-area-inset-bottom))',
      transform: 'translateX(-50%)',
      zIndex: '2147483647',
      width: 'min(calc(100% - 28px), 480px)',
      padding: '12px 14px',
      borderRadius: '14px',
      border: error ? '1px solid rgba(238,139,139,.35)' : '1px solid rgba(78,208,160,.28)',
      background: error ? 'rgba(42,20,23,.98)' : 'rgba(13,29,25,.98)',
      color: '#F3F0E9',
      fontSize: '13px',
      lineHeight: '1.35',
      boxShadow: '0 16px 42px rgba(0,0,0,.42)',
      textAlign: 'center',
      pointerEvents: 'none'
    });
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), error ? 5000 : 3000);
  } catch {}
}

function requestNativeDownload(access) {
  const payload = { url: access.download_url, file_name: access.filename || 'KORGAN.docx' };

  try {
    const tg = window.Telegram?.WebApp;
    if (tg && typeof tg.downloadFile === 'function') {
      return new Promise((resolve) => {
        let settled = false;
        const finish = (value) => {
          if (settled) return;
          settled = true;
          resolve(Boolean(value));
        };
        const timer = setTimeout(() => finish(false), 2200);
        try {
          tg.downloadFile(payload, (accepted) => {
            clearTimeout(timer);
            finish(accepted);
          });
        } catch {
          clearTimeout(timer);
          finish(false);
        }
      });
    }
  } catch {}

  try {
    if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === 'function') {
      window.TelegramWebviewProxy.postEvent('web_app_request_file_download', JSON.stringify(payload));
      return Promise.resolve(true);
    }
  } catch {}

  try {
    if (window.external && typeof window.external.notify === 'function') {
      window.external.notify(JSON.stringify({ eventType: 'web_app_request_file_download', eventData: payload }));
      return Promise.resolve(true);
    }
  } catch {}

  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(JSON.stringify({ eventType: 'web_app_request_file_download', eventData: payload }), '*');
      return Promise.resolve(true);
    }
  } catch {}

  return Promise.resolve(false);
}

function directDownload(url) {
  try {
    const frame = document.createElement('iframe');
    frame.hidden = true;
    frame.setAttribute('aria-hidden', 'true');
    frame.src = url;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 20000);
    return true;
  } catch {
    return false;
  }
}

async function download(button) {
  if (button.dataset.korganDownloadV4Busy === '1') return;
  const caseId = resolveCaseId(button);
  if (!caseId) {
    notify(isKazakh() ? 'Іс нөмірін анықтау мүмкін болмады' : 'Не удалось определить номер дела', true);
    ping('case-id-missing');
    return;
  }

  button.dataset.korganDownloadV4Busy = '1';
  const disabled = button.disabled;
  button.disabled = true;
  ping('click', caseId);

  try {
    const access = await createDocumentAccess(caseId);
    if (!access?.download_url) throw new Error(isKazakh() ? 'Жүктеу сілтемесі алынбады' : 'Не получена ссылка на скачивание');
    ping('access-ok', caseId);

    const nativeStarted = await requestNativeDownload(access);
    if (nativeStarted) {
      ping('native-started', caseId);
      notify(isKazakh() ? 'DOCX жүктеу басталды' : 'Скачивание DOCX началось');
      return;
    }

    if (directDownload(access.download_url)) {
      ping('direct-started', caseId);
      notify(isKazakh() ? 'DOCX жүктеу басталды' : 'Скачивание DOCX началось');
      return;
    }

    throw new Error(isKazakh() ? 'Құжатты жүктеу мүмкін болмады' : 'Не удалось запустить скачивание документа');
  } catch (error) {
    ping('error', error?.message || 'unknown');
    notify(error?.message || (isKazakh() ? 'Құжатты жүктеу мүмкін болмады' : 'Не удалось скачать документ'), true);
  } finally {
    button.dataset.korganDownloadV4Busy = '0';
    button.disabled = disabled;
  }
}

function onClick(event) {
  const button = event.target?.closest?.('button');
  if (!button || !isDownloadButton(button)) return;

  // Own the download before legacy v3/v2 handlers can fall back to Telegram sendDocument.
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  download(button);
}

document.addEventListener('click', onClick, { capture: true });
ping('installed');
