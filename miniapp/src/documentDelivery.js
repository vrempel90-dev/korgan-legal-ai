const LINK_OPEN_ERROR = 'Не удалось открыть ссылку на документ';

/** Открывает подписанную ссылку через нативную загрузку Telegram, если она есть. */
export async function openSignedDocument(url, filename, {
  telegram = globalThis.window?.Telegram?.WebApp ?? null,
  openWindow = globalThis.window?.open?.bind(globalThis.window),
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
  if (typeof openWindow !== 'function') return false;
  return Boolean(openWindow(url, '_blank', 'noopener,noreferrer'));
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
