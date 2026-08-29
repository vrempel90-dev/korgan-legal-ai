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

function downloadPlatform() {
  const platform = String(window.Telegram?.WebApp?.platform || '').toLowerCase();
  const ua = String(navigator.userAgent || '').toLowerCase();
  if (platform === 'ios' || /iphone|ipad|ipod/.test(ua)) return 'ios';
  if (platform === 'android' || /android/.test(ua)) return 'android';
  return 'other';
}

function removeDownloadGuide() {
  document.querySelector('.korgan-download-guide-v1')?.remove();
}

function showDownloadGuide(filename = 'KORGAN.docx') {
  try {
    removeDownloadGuide();
    const kk = isKazakh();
    const platform = downloadPlatform();
    const guide = document.createElement('section');
    guide.className = 'korgan-download-guide-v1';
    guide.setAttribute('role', 'dialog');
    guide.setAttribute('aria-modal', 'false');

    const title = kk ? 'Құжатты қайдан табуға болады' : 'Где найти документ';
    let device = kk ? 'Құрылғы' : 'Устройство';
    let instruction = kk
      ? 'Жүктелген файлды құрылғыңыздың «Файлдар» немесе «Жүктеулер» бөлімінен табуға болады.'
      : 'Скачанный файл можно найти в приложении «Файлы» или в разделе «Загрузки».';

    if (platform === 'android') {
      device = 'Android';
      instruction = kk
        ? '«Файлдар» → «Жүктеулер». Егер файл көрінбесе, «Құжаттар» немесе «Telegram» бумасын тексеріңіз.'
        : 'Откройте «Файлы» → «Загрузки». Если файла нет, проверьте «Документы» или папку «Telegram».';
    } else if (platform === 'ios') {
      device = 'iPhone';
      instruction = kk
        ? '«Файлдар» → «Соңғылар». Егер файл көрінбесе: «Шолу» → «iCloud Drive» немесе «Менің iPhone-ымда» → «Жүктеулер».'
        : 'Откройте «Файлы» → «Недавние». Если файла нет: «Обзор» → «iCloud Drive» или «На iPhone» → «Загрузки».';
    }

    const safeName = document.createElement('span');
    safeName.className = 'korgan-download-guide-file';
    safeName.textContent = filename || 'KORGAN.docx';

    guide.innerHTML = `
      <div class="korgan-download-guide-head">
        <div>
          <small>${device}</small>
          <strong>${title}</strong>
        </div>
        <button type="button" class="korgan-download-guide-close" aria-label="${kk ? 'Жабу' : 'Закрыть'}">×</button>
      </div>
      <p class="korgan-download-guide-text"></p>
      <div class="korgan-download-guide-file-wrap"><span class="korgan-download-guide-doc">DOCX</span></div>
    `;
    guide.querySelector('.korgan-download-guide-text').textContent = instruction;
    guide.querySelector('.korgan-download-guide-file-wrap').appendChild(safeName);
    guide.querySelector('.korgan-download-guide-close').addEventListener('click', removeDownloadGuide);

    Object.assign(guide.style, {
      position: 'fixed',
      left: '14px',
      right: '14px',
      bottom: 'calc(18px + env(safe-area-inset-bottom))',
      zIndex: '2147483646',
      maxWidth: '520px',
      margin: '0 auto',
      padding: '15px',
      borderRadius: '18px',
      border: '1px solid rgba(212,174,43,.22)',
      background: 'rgba(13,18,24,.98)',
      color: '#F3F0E9',
      boxShadow: '0 22px 58px rgba(0,0,0,.46)',
      backdropFilter: 'blur(18px)'
    });

    const head = guide.querySelector('.korgan-download-guide-head');
    Object.assign(head.style, { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' });
    const headText = head.querySelector('div');
    Object.assign(headText.style, { display: 'flex', flexDirection: 'column', gap: '3px', minWidth: '0' });
    const small = head.querySelector('small');
    Object.assign(small.style, { color: '#D4AE2B', fontSize: '10px', fontWeight: '800', letterSpacing: '.1em', textTransform: 'uppercase' });
    const strong = head.querySelector('strong');
    Object.assign(strong.style, { fontSize: '15px', lineHeight: '1.25' });
    const close = guide.querySelector('.korgan-download-guide-close');
    Object.assign(close.style, { width: '32px', height: '32px', borderRadius: '10px', border: '1px solid rgba(255,255,255,.1)', background: 'rgba(255,255,255,.04)', color: '#AEB6BF', fontSize: '22px', lineHeight: '1', cursor: 'pointer' });
    const text = guide.querySelector('.korgan-download-guide-text');
    Object.assign(text.style, { margin: '11px 0 12px', color: '#AAB3BC', fontSize: '12.5px', lineHeight: '1.48' });
    const fileWrap = guide.querySelector('.korgan-download-guide-file-wrap');
    Object.assign(fileWrap.style, { display: 'flex', alignItems: 'center', gap: '8px', minWidth: '0' });
    const doc = guide.querySelector('.korgan-download-guide-doc');
    Object.assign(doc.style, { flex: '0 0 auto', padding: '5px 7px', borderRadius: '8px', background: 'rgba(78,208,160,.09)', border: '1px solid rgba(78,208,160,.16)', color: '#6ED7AD', fontSize: '9px', fontWeight: '800', letterSpacing: '.08em' });
    Object.assign(safeName.style, { minWidth: '0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#D8DDE2', fontSize: '11px' });

    document.body.appendChild(guide);
    window.setTimeout(() => {
      if (guide.isConnected) guide.remove();
    }, 14000);
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
      notify(isKazakh() ? 'Құжат жүктелуде' : 'Документ скачивается');
      showDownloadGuide(access.filename);
      return;
    }

    if (directDownload(access.download_url)) {
      ping('direct-started', caseId);
      notify(isKazakh() ? 'Құжат жүктелуде' : 'Документ скачивается');
      showDownloadGuide(access.filename);
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

  // Own the download before legacy handlers can fall back to Telegram sendDocument.
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  download(button);
}

document.addEventListener('click', onClick, { capture: true });
ping('installed');
