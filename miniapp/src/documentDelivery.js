const LINK_OPEN_ERROR = 'Не удалось открыть ссылку на документ';
const FRAME_LIFETIME_MS = 60000;

/**
 * Забирает вложение скрытой рамкой, когда всплывающее окно заблокировано.
 * Ответ сервера помечен как attachment, поэтому рамка инициирует скачивание и
 * не уводит пользователя из Mini App.
 */
function downloadInFrame(url, page) {
  if (!page?.body || typeof page.createElement !== 'function') return false;
  const frame = page.createElement('iframe');
  frame.hidden = true;
  frame.style.display = 'none';
  frame.src = url;
  page.body.appendChild(frame);
  if (typeof setTimeout === 'function') {
    setTimeout(() => { try { frame.remove(); } catch { /* страница уже сменилась */ } }, FRAME_LIFETIME_MS);
  }
  return true;
}

/** Открывает подписанную ссылку через нативную загрузку Mini App, если она есть. */
export async function openSignedDocument(url, filename, {
  telegram = globalThis.window?.Telegram?.WebApp ?? null,
  openWindow = globalThis.window?.open?.bind(globalThis.window),
  documentRef = globalThis.document ?? null,
} = {}) {
  if (typeof telegram?.downloadFile === 'function') {
    return new Promise((resolve) => {
      try {
        telegram.downloadFile(
          { url, file_name: filename || 'KORGAN_document.docx' },
          (downloadAccepted) => resolve(downloadAccepted === true),
        );
      } catch {
        resolve(false);
      }
    });
  }
  if (typeof openWindow === 'function' && openWindow(url, '_blank', 'noopener,noreferrer')) return true;
  return downloadInFrame(url, documentRef);
}

function requireCaseId(caseId) {
  const value = String(caseId || '').trim();
  if (!value) throw new Error('Не выбран документ для скачивания');
  return value;
}

async function deliverByLink(caseId, api, openUrl) {
  const access = await api.documentAccess(caseId);
  const url = String(access?.download_url || '').trim();
  if (!access?.ok || !/^https:\/\//i.test(url)) {
    throw new Error('Ссылка на документ не получена');
  }

  const opened = await openUrl(url, access.filename || 'KORGAN_document.docx');
  if (opened === false) throw new Error(LINK_OPEN_ERROR);

  return {
    via: 'link',
    filename: access.filename || 'KORGAN_document.docx',
    url,
  };
}

/**
 * Готовый документ всегда выдаётся непосредственно из Mini App по короткоживущей
 * подписанной HTTPS-ссылке. Telegram-бот не является каналом доставки и никогда
 * не получает файл, даже когда приложение открыто внутри Telegram.
 */
export async function deliverDocument(caseId, { api, openUrl }) {
  const id = requireCaseId(caseId);
  if (!api || typeof api.documentAccess !== 'function') {
    throw new Error('Скачивание документов не настроено');
  }
  if (typeof openUrl !== 'function') throw new Error('Открытие документа не настроено');
  return deliverByLink(id, api, openUrl);
}
