/**
 * Готовый документ должен открыться от одного нажатия — и остаться у клиента.
 *
 * Что было
 * --------
 * Кнопка называлась «Скачать документ» и делала ровно это: в браузере отдавала
 * вложение, в Telegram просила бота прислать файл в чат. В обоих случаях
 * человек, заплативший за документ, его не видел — ему предлагали найти файл в
 * загрузках или уйти в другой чат и открыть вложение оттуда.
 *
 * При этом сервер с самого начала отдаёт две ссылки за один запрос:
 * `preview_url` — тот же документ, отрисованный в HTML и открывающийся в любом
 * WebView, — и `download_url` с вложением. Клиент не использовал первую ни в
 * одном из путей.
 *
 * Что делает модуль
 * -----------------
 * Один запрос за доступом, затем два независимых действия: открыть просмотр и
 * отдать файл. Просмотр занимает единственное окно, которое браузер разрешает
 * открыть по нажатию; файл забирается способом, окна не требующим, — нативной
 * загрузкой Telegram или скрытой рамкой. Порядок именно такой: главное для
 * человека — увидеть документ.
 *
 * Границы платформы
 * -----------------
 * Открыть локальный файл после скачивания из WebView нельзя, и обходить это
 * хаками здесь никто не пытается. Поэтому «открылся» означает открытый
 * серверный просмотр того же документа, а «сохранился» — файл у пользователя.
 */

const OPEN_FAILED = 'Не удалось открыть документ. Попробуйте скачать ещё раз.';
const SAVED_NOT_OPENED = 'Документ скачан. Откройте его из загрузок устройства.';
const FRAME_LIFETIME_MS = 60000;
const DEFAULT_FILENAME = 'KORGAN_document.docx';

export { OPEN_FAILED, SAVED_NOT_OPENED };

/**
 * Забирает вложение скрытой рамкой.
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

/**
 * Открывает просмотр документа — единственное окно, которое мы вправе занять.
 *
 * Внутри Telegram окно открывает сам клиент: `window.open` в его WebView либо
 * блокируется, либо уводит из Mini App без возврата.
 */
export function openDocumentPreview(url, {
  telegram = globalThis.window?.Telegram?.WebApp ?? null,
  openWindow = globalThis.window?.open?.bind(globalThis.window),
} = {}) {
  const link = String(url || '').trim();
  if (!link) return false;

  if (typeof telegram?.openLink === 'function') {
    try {
      telegram.openLink(link);
      return true;
    } catch {
      // Клиент отказался открывать ссылку — пробуем обычным окном ниже.
    }
  }
  if (typeof openWindow === 'function') {
    try {
      if (openWindow(link, '_blank', 'noopener,noreferrer')) return true;
    } catch {
      // Всплывающее окно заблокировано.
    }
  }
  return false;
}

/**
 * Отдаёт файл пользователю, не занимая второго окна.
 *
 * Второе окно подряд браузеры и Telegram блокируют, поэтому здесь только
 * способы, которым окно не нужно: нативная загрузка Telegram и скрытая рамка.
 */
export async function saveDocumentFile(url, filename, {
  telegram = globalThis.window?.Telegram?.WebApp ?? null,
  documentRef = globalThis.document ?? null,
} = {}) {
  const link = String(url || '').trim();
  if (!link) return false;

  if (telegram) {
    // Внутри Telegram файл отдаёт только нативная загрузка. Скрытая рамка в его
    // WebView срабатывает вхолостую: разметка вставляется, ошибки нет, файла
    // тоже нет — и отчёт об успехе был бы ложным, а из-за него не сработал бы
    // единственный надёжный запасной путь, досылка документа ботом в чат.
    if (typeof telegram.downloadFile !== 'function') return false;
    return new Promise((resolve) => {
      try {
        telegram.downloadFile(
          { url: link, file_name: filename || DEFAULT_FILENAME },
          (downloadAccepted) => resolve(downloadAccepted === true),
        );
      } catch {
        resolve(false);
      }
    });
  }
  return downloadInFrame(link, documentRef);
}

/**
 * Одно нажатие: документ открывается и одновременно остаётся у пользователя.
 *
 * Неудача одного из двух действий не отменяет другого — они независимы, и
 * скачанный, но не открывшийся документ клиенту всё же доставлен.
 */
export async function openDocumentForClient({ previewUrl, downloadUrl, filename }, environment = {}) {
  const opened = openDocumentPreview(previewUrl, environment);
  const saved = await saveDocumentFile(downloadUrl, filename, environment);
  return { opened, saved };
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
    filename: result.filename || DEFAULT_FILENAME,
    message: result.message || 'Документ отправлен вам в чат с ботом KORGAN.',
  };
}

function requireHttps(value, what) {
  const url = String(value || '').trim();
  if (!/^https:\/\//i.test(url)) throw new Error(`Ссылка на ${what} не получена`);
  return url;
}

/**
 * Досылает файл в чат с ботом, когда сохранить его на устройство не удалось.
 *
 * Отказ здесь не отменяет уже открытого документа: главное действие кнопки
 * выполнено, и объявлять его неудачей из-за неотправленной копии нельзя.
 */
async function sendToChatQuietly(caseId, api) {
  if (typeof api.sendDocumentToTelegram !== 'function') return null;
  try {
    return requireTelegramResult(await api.sendDocumentToTelegram(caseId));
  } catch {
    return null;
  }
}

/**
 * Открывает готовый документ и отдаёт его файл — за один запрос к серверу.
 *
 * Документ уже готов и оплачен: сюда приходят только за ссылками на него.
 * Никакой повторной подготовки, второй задачи и второго списания здесь нет и
 * быть не может — `documentAccess` только подписывает доступ к уже сохранённому
 * файлу.
 */
export async function deliverDocument(caseId, { insideTelegram, api, openDocument }) {
  const id = requireCaseId(caseId);
  if (!api || typeof api.documentAccess !== 'function') {
    throw new Error('Доставка документов не настроена');
  }
  if (typeof openDocument !== 'function') throw new Error('Открытие документа не настроено');

  const access = await api.documentAccess(id);
  if (!access?.ok) throw new Error('Ссылка на документ не получена');
  const filename = access.filename || DEFAULT_FILENAME;
  const previewUrl = requireHttps(access.preview_url, 'просмотр документа');
  const downloadUrl = requireHttps(access.download_url, 'скачивание документа');

  const { opened, saved } = (await openDocument({ previewUrl, downloadUrl, filename })) || {};
  const result = { via: opened ? 'preview' : 'download', filename, opened, saved: Boolean(saved) };

  // Файл не сохранился на устройство. В Telegram остаётся надёжный путь: бот
  // присылает документ в чат, где он и открывается штатным просмотрщиком, и
  // сохраняется. Это единственный способ отдать файл клиентам без нативной
  // загрузки, и он же спасает случай, когда не открылось вообще ничего.
  if (!result.saved && insideTelegram) {
    const delivered = await sendToChatQuietly(id, api);
    if (delivered) {
      result.saved = true;
      result.message = delivered.message;
      if (!opened) result.via = 'telegram';
    }
  }

  if (!result.opened && !result.saved) throw new Error(OPEN_FAILED);
  if (!result.opened && result.via === 'download') result.message = SAVED_NOT_OPENED;
  return result;
}
