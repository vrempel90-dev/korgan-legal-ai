const LINK_OPEN_ERROR = 'Не удалось открыть ссылку на документ';
const FRAME_LIFETIME_MS = 60000;

/**
 * Забирает вложение скрытой рамкой, когда всплывающее окно заблокировано.
 *
 * Ссылку выдаёт сервер, и запрос за ней проходит между нажатием и открытием
 * окна: разрешение открывать окна живёт «по нажатию» и такого ожидания не
 * переживает — Safari отзывает его сразу, Chrome через несколько секунд. Ответ
 * сервера помечен как вложение, поэтому рамка его скачивает и никуда не уводит
 * со страницы, а блокировщик всплывающих окон её не касается.
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

/** Открывает подписанную ссылку через нативную загрузку Telegram, если она есть. */
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
  // Окно остаётся первым способом: истёкшую ссылку сервер объясняет прямо в
  // открытой вкладке, а рамка такой ответ проглотила бы молча.
  if (typeof openWindow === 'function' && openWindow(url, '_blank', 'noopener,noreferrer')) return true;
  return downloadInFrame(url, documentRef);
}

function requireCaseId(caseId) {
  const value = String(caseId || '').trim();
  if (!value) throw new Error('Не выбрано дело для отправки документа');
  return value;
}

function requireTelegramResult(result) {
  if (!result?.ok || result?.delivered_to !== 'telegram') {
    throw new Error('Telegram не подтвердил отправку документа');
  }
  return {
    via: 'telegram',
    filename: result.filename || 'KORGAN_document.docx',
    message: result.message || 'Документ отправлен вам в чат с ботом KORGAN.',
  };
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
 * Доставляет готовый документ по пути, который поддерживает среда пользователя.
 *
 * В Telegram файл присылает бот: только его ответ подтверждает доставку. В
 * обычном браузере клиент получает короткоживущую подписанную HTTPS-ссылку.
 */
export async function deliverDocument(caseId, { insideTelegram, api, openUrl }) {
  const id = requireCaseId(caseId);
  if (!api || typeof api.sendDocumentToTelegram !== 'function' || typeof api.documentAccess !== 'function') {
    throw new Error('Доставка документов не настроена');
  }
  if (typeof openUrl !== 'function') throw new Error('Открытие документа не настроено');

  if (insideTelegram) {
    return requireTelegramResult(await api.sendDocumentToTelegram(id));
  }
  return deliverByLink(id, api, openUrl);
}
