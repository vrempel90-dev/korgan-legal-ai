/**
 * Нажал один раз — документ открылся, и его файл остался у пользователя.
 *
 * Кнопка называлась «Скачать документ» и делала ровно это: в браузере отдавала
 * вложение, в Telegram просила бота прислать файл в чат. В обоих случаях
 * человек, заплативший за документ, его не видел — ему предлагали найти файл в
 * загрузках или уйти в другой чат. При этом сервер с самого начала отдаёт за
 * один запрос две ссылки: `preview_url` с готовым просмотром и `download_url`
 * с вложением, — и клиент не использовал первую ни в одном из путей.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  OPEN_FAILED,
  SAVED_NOT_OPENED,
  deliverDocument,
  openDocumentForClient,
  openDocumentPreview,
  saveDocumentFile,
} from '../src/documentDelivery.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

const ACCESS = {
  ok: true,
  filename: 'KORGAN_iskovoe_zayavlenie.docx',
  download_url: 'https://api.korgan.kz/miniapp/document/download?token=abc',
  preview_url: 'https://api.korgan.kz/miniapp/document/preview?token=abc',
};

function httpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

/** Двойник страницы: скрытая рамка — единственный способ скачать без окна. */
function fakeDocument() {
  const created = [];
  const body = { children: [], appendChild(node) { this.children.push(node); } };
  return {
    created,
    body,
    createElement(tag) {
      const node = { tag, style: {}, remove() { body.children = body.children.filter(item => item !== node); } };
      created.push(node);
      return node;
    },
  };
}

/** Готовый набор двойников для одного нажатия. */
function environment({ telegram = null, openWindow = () => ({}), documentRef = fakeDocument() } = {}) {
  return { telegram, openWindow, documentRef };
}

function apiWith(overrides = {}) {
  const calls = { access: 0, telegram: 0, generate: 0 };
  const api = {
    calls,
    documentAccess: async () => { calls.access += 1; return ACCESS; },
    sendDocumentToTelegram: async () => {
      calls.telegram += 1;
      return { ok: true, delivered_to: 'telegram', filename: ACCESS.filename, message: 'Документ отправлен вам в чат с ботом KORGAN.' };
    },
    generateDocument: async () => { calls.generate += 1; },
    ...overrides,
  };
  return api;
}

// --- одно нажатие ---------------------------------------------------------

test('одно нажатие открывает документ и сохраняет файл', async () => {
  const opened = [];
  const api = apiWith();
  const result = await deliverDocument('KOR-1', {
    insideTelegram: false,
    api,
    openDocument: async (access) => {
      opened.push(access);
      return { opened: true, saved: true };
    },
  });

  assert.equal(result.opened, true);
  assert.equal(result.saved, true);
  assert.equal(result.filename, ACCESS.filename);
  assert.deepEqual(opened, [{
    previewUrl: ACCESS.preview_url,
    downloadUrl: ACCESS.download_url,
    filename: ACCESS.filename,
  }]);
});

test('за ссылками ходят ровно один раз и ничего не генерируют заново', async () => {
  const api = apiWith();
  await deliverDocument('KOR-1', {
    insideTelegram: false,
    api,
    openDocument: async () => ({ opened: true, saved: true }),
  });

  assert.equal(api.calls.access, 1, 'ссылка на документ запрошена не один раз');
  assert.equal(api.calls.generate, 0, 'документ подготовлен повторно');
  assert.equal(api.calls.telegram, 0, 'лишняя отправка ботом при успешном открытии');
});

test('повторное нажатие не создаёт нового документа и новой задачи', async () => {
  const api = apiWith();
  const open = async () => ({ opened: true, saved: true });

  await deliverDocument('KOR-1', { insideTelegram: false, api, openDocument: open });
  await deliverDocument('KOR-1', { insideTelegram: false, api, openDocument: open });

  assert.equal(api.calls.access, 2, 'каждое нажатие подписывает доступ заново');
  assert.equal(api.calls.generate, 0, 'повторное нажатие запустило подготовку документа');
});

test('успешное открытие ничего не сообщает лишнего', async () => {
  const result = await deliverDocument('KOR-1', {
    insideTelegram: false,
    api: apiWith(),
    openDocument: async () => ({ opened: true, saved: true }),
  });
  assert.equal(result.message, undefined);
});

// --- границы платформы ----------------------------------------------------

test('скачанный, но не открывшийся документ не выдаётся за ошибку', async () => {
  const result = await deliverDocument('KOR-1', {
    insideTelegram: false,
    api: apiWith(),
    openDocument: async () => ({ opened: false, saved: true }),
  });

  assert.equal(result.via, 'download');
  assert.equal(result.message, SAVED_NOT_OPENED);
});

test('в Telegram несохранённый файл досылается ботом в чат', async () => {
  const api = apiWith();
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    api,
    openDocument: async () => ({ opened: true, saved: false }),
  });

  assert.equal(result.opened, true);
  assert.equal(result.saved, true);
  assert.equal(api.calls.telegram, 1);
  assert.match(result.message, /чат с ботом/);
});

test('отказ досылки не отменяет уже открытого документа', async () => {
  const api = apiWith({
    sendDocumentToTelegram: async () => {
      throw httpError(409, 'Откройте бота KORGAN в Telegram и нажмите «Старт», затем повторите отправку.');
    },
  });
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    api,
    openDocument: async () => ({ opened: true, saved: false }),
  });

  assert.equal(result.opened, true);
  assert.equal(result.saved, false);
});

test('когда не вышло ни открыть, ни сохранить, в Telegram работает бот', async () => {
  const api = apiWith();
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    api,
    openDocument: async () => ({ opened: false, saved: false }),
  });

  assert.equal(result.via, 'telegram');
  assert.equal(api.calls.telegram, 1);
});

test('полная неудача даёт клиенту понятный текст без технических подробностей', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      api: apiWith(),
      openDocument: async () => ({ opened: false, saved: false }),
    }),
    (error) => {
      assert.equal(error.message, OPEN_FAILED);
      assert.doesNotMatch(error.message, /http|status|token|url|Error|\d{3}/i);
      return true;
    },
  );
});

// --- как открывается и как сохраняется ------------------------------------

test('внутри Telegram ссылку открывает сам клиент, а не window.open', () => {
  const links = [];
  const windows = [];
  const opened = openDocumentPreview(ACCESS.preview_url, {
    telegram: { openLink: (url) => links.push(url) },
    openWindow: (url) => { windows.push(url); return {}; },
  });

  assert.equal(opened, true);
  assert.deepEqual(links, [ACCESS.preview_url]);
  assert.deepEqual(windows, [], 'в Telegram WebView открыто постороннее окно');
});

test('обычный браузер открывает просмотр новой вкладкой', () => {
  const opened = [];
  const result = openDocumentPreview(ACCESS.preview_url, {
    telegram: null,
    openWindow: (url, target, features) => { opened.push([url, target, features]); return {}; },
  });

  assert.equal(result, true);
  assert.deepEqual(opened, [[ACCESS.preview_url, '_blank', 'noopener,noreferrer']]);
});

test('заблокированное окно честно сообщает, что просмотр не открылся', () => {
  assert.equal(openDocumentPreview(ACCESS.preview_url, { telegram: null, openWindow: () => null }), false);
});

test('файл сохраняется нативной загрузкой Telegram, когда она есть', async () => {
  const asked = [];
  const saved = await saveDocumentFile(ACCESS.download_url, ACCESS.filename, {
    telegram: {
      downloadFile: (params, callback) => { asked.push(params); callback(true); },
    },
    documentRef: fakeDocument(),
  });

  assert.equal(saved, true);
  assert.deepEqual(asked, [{ url: ACCESS.download_url, file_name: ACCESS.filename }]);
});

test('отказ пользователя от нативной загрузки не выдаётся за сохранение', async () => {
  const saved = await saveDocumentFile(ACCESS.download_url, ACCESS.filename, {
    telegram: { downloadFile: (_params, callback) => callback(false) },
  });
  assert.equal(saved, false);
});

test('без нативной загрузки файл забирает скрытая рамка, а не второе окно', async () => {
  const page = fakeDocument();
  const saved = await saveDocumentFile(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    documentRef: page,
  });

  assert.equal(saved, true);
  assert.equal(page.created.length, 1);
  assert.equal(page.created[0].tag, 'iframe');
  assert.equal(page.created[0].src, ACCESS.download_url);
});

test('без страницы и без нативной загрузки сохранение честно проваливается', async () => {
  assert.equal(
    await saveDocumentFile(ACCESS.download_url, ACCESS.filename, { telegram: null, documentRef: null }),
    false,
  );
});

test('открытие и сохранение идут вместе и независимо', async () => {
  const page = fakeDocument();
  const windows = [];
  const result = await openDocumentForClient(
    { previewUrl: ACCESS.preview_url, downloadUrl: ACCESS.download_url, filename: ACCESS.filename },
    environment({ telegram: null, openWindow: (url) => { windows.push(url); return {}; }, documentRef: page }),
  );

  assert.deepEqual(result, { opened: true, saved: true });
  assert.deepEqual(windows, [ACCESS.preview_url], 'просмотр открыт не той ссылкой');
  assert.equal(page.created[0].src, ACCESS.download_url, 'скачана не та ссылка');
  assert.equal(page.created.length, 1, 'на сохранение потрачено больше одной рамки');
});

test('имя файла доходит до нативной загрузки без изменений', async () => {
  const asked = [];
  await openDocumentForClient(
    { previewUrl: ACCESS.preview_url, downloadUrl: ACCESS.download_url, filename: 'KORGAN_dosudebnaya_pretenziya.docx' },
    environment({ telegram: { openLink: () => {}, downloadFile: (params, cb) => { asked.push(params.file_name); cb(true); } } }),
  );
  assert.deepEqual(asked, ['KORGAN_dosudebnaya_pretenziya.docx']);
});

test('формат файла ничем не ограничен: PDF пройдёт тем же путём', async () => {
  const asked = [];
  const result = await openDocumentForClient(
    { previewUrl: 'https://api.korgan.kz/p?token=x', downloadUrl: 'https://api.korgan.kz/d?token=x', filename: 'KORGAN_document.pdf' },
    environment({ telegram: { openLink: () => {}, downloadFile: (params, cb) => { asked.push(params.file_name); cb(true); } } }),
  );

  assert.deepEqual(result, { opened: true, saved: true });
  assert.deepEqual(asked, ['KORGAN_document.pdf']);
});

// --- отказы сервера -------------------------------------------------------

test('документа ещё нет — это ошибка, а не тихий успех', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      api: apiWith({
        documentAccess: async () => { throw httpError(404, 'Документ по этому делу ещё не готов'); },
      }),
      openDocument: async () => ({ opened: true, saved: true }),
    }),
    /ещё не готов/,
  );
});

test('ответ без ссылки на просмотр не выдаётся за открытый документ', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      api: apiWith({
        documentAccess: async () => ({ ok: true, filename: ACCESS.filename, download_url: ACCESS.download_url }),
      }),
      openDocument: async () => ({ opened: true, saved: true }),
    }),
    /ссылк/i,
  );
});

test('ответ без ссылки на файл тоже отвергается', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      api: apiWith({
        documentAccess: async () => ({ ok: true, filename: ACCESS.filename, preview_url: ACCESS.preview_url }),
      }),
      openDocument: async () => ({ opened: true, saved: true }),
    }),
    /ссылк/i,
  );
});

test('дело без идентификатора не отправляется в сеть', async () => {
  const api = apiWith();
  await assert.rejects(
    deliverDocument('', { insideTelegram: false, api, openDocument: async () => ({ opened: true, saved: true }) }),
  );
  assert.equal(api.calls.access, 0);
});

// --- контракт приложения --------------------------------------------------

test('приложение не собирает файл из base64 в браузере', () => {
  // Путь blob + <a download> в Telegram WebView проваливается молча.
  const code = readFileSync(join(src, 'main.jsx'), 'utf8');
  assert.ok(!/createObjectURL/.test(code), 'main.jsx всё ещё собирает blob для скачивания');
  assert.ok(!/downloadBase64/.test(code), 'main.jsx всё ещё скачивает документ из base64');
});

test('кнопка ведёт через один серверный доступ и знает про Telegram', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.match(api, /\/document\/access/);
  assert.match(api, /\/document\/telegram/);
  assert.match(app, /deliverDocument\(activeCase\.id/);
  // Внутри Telegram ссылку обязан открывать сам клиент.
  assert.match(app, /openDocumentForClient\(access, \{ telegram: tg \}\)/);
});

test('нажатие называет своё действие, а не общую занятость', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  assert.match(app, /setBusy\('deliver'\)/, 'открытие документа не отличает себя от прочей занятости');
  const buttons = app.split('\n').filter(line => line.includes('onClick={deliverActiveDocument}'));
  assert.ok(buttons.length >= 1, 'кнопка открытия документа не найдена');
  for (const line of buttons) {
    assert.match(line, /busyAction === 'deliver'/, 'кнопка объявляет своим любое чужое действие');
  }
});

test('в старом Telegram без нативной загрузки рамка не выдаётся за сохранение', async () => {
  // Скрытая рамка в Telegram WebView срабатывает вхолостую: файла нет и ошибки
  // нет. Ложный успех здесь отменил бы досылку ботом — единственный путь, по
  // которому файл действительно доходит до пользователя в таком клиенте.
  const page = fakeDocument();
  const saved = await saveDocumentFile(ACCESS.download_url, ACCESS.filename, {
    telegram: { openLink: () => {} },
    documentRef: page,
  });

  assert.equal(saved, false);
  assert.deepEqual(page.created, [], 'в Telegram создана бесполезная рамка');
});

test('старый Telegram: документ открыт просмотром, файл дошёл ботом', async () => {
  const api = apiWith();
  const links = [];
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    api,
    openDocument: (access) => openDocumentForClient(access, {
      telegram: { openLink: (url) => links.push(url) },
      documentRef: fakeDocument(),
    }),
  });

  assert.deepEqual(links, [ACCESS.preview_url], 'просмотр не открылся');
  assert.equal(result.saved, true, 'файл не дошёл до пользователя');
  assert.equal(api.calls.telegram, 1);
  assert.equal(api.calls.access, 1, 'ссылка запрошена не один раз');
});
