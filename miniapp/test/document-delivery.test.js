/**
 * Документ обязан дойти до пользователя или сказать, почему не дошёл.
 *
 * Скачивание собиралось из base64 в blob и запускалось кликом по <a download>.
 * Встроенный браузер Telegram этот путь не поддерживает: клик проходит,
 * промис исполняется, файла нет и ошибки нет. Именно поэтому на бэкенде
 * появились korgan/miniapp_telegram_delivery.py (файл присылает бот) и
 * korgan/miniapp_document_access.py (подписанная https-ссылка) — но клиент не
 * вызывал ни то, ни другое.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { deliverDocument, openSignedDocument } from '../src/documentDelivery.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

const ACCESS = {
  ok: true,
  filename: 'KORGAN_claim.docx',
  download_url: 'https://api.korgan.kz/miniapp/document/download?token=abc',
  preview_url: 'https://api.korgan.kz/miniapp/document/preview?token=abc',
};

function httpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

test('внутри Telegram документ присылает бот', async () => {
  const opened = [];
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    openUrl: (url) => opened.push(url),
    api: {
      sendDocumentToTelegram: async () => ({
        ok: true,
        delivered_to: 'telegram',
        message: 'Документ отправлен вам в чат с ботом KORGAN.',
      }),
      documentAccess: async () => {
        throw new Error('подписанная ссылка здесь не нужна');
      },
    },
  });

  assert.equal(result.via, 'telegram');
  assert.equal(result.message, 'Документ отправлен вам в чат с ботом KORGAN.');
  assert.deepEqual(opened, []);
});

test('ошибка настройки бота не маскируется запасным сценарием', async () => {
  let accessCalls = 0;
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: true,
      openUrl: () => {},
      api: {
        sendDocumentToTelegram: async () => {
          throw httpError(503, 'Отправка в Telegram не настроена');
        },
        documentAccess: async () => {
          accessCalls += 1;
          return ACCESS;
        },
      },
    }),
    /не настроена/,
  );
  assert.equal(accessCalls, 0);
});

test('вне Telegram документ выдаётся по подписанной ссылке', async () => {
  const opened = [];
  let telegramCalls = 0;
  const result = await deliverDocument('KOR-1', {
    insideTelegram: false,
    openUrl: (url) => {
      opened.push(url);
      return true;
    },
    api: {
      sendDocumentToTelegram: async () => {
        telegramCalls += 1;
        return { ok: true, delivered_to: 'telegram' };
      },
      documentAccess: async () => ACCESS,
    },
  });

  assert.equal(result.via, 'link');
  assert.equal(result.filename, 'KORGAN_claim.docx');
  assert.deepEqual(opened, [ACCESS.download_url]);
  assert.equal(telegramCalls, 0);
});

test('заблокированное открытие ссылки считается ошибкой доставки', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      openUrl: () => false,
      api: {
        sendDocumentToTelegram: async () => ({ ok: true }),
        documentAccess: async () => ACCESS,
      },
    }),
    /открыть/i,
  );
});

test('Telegram openLink не считается подтверждением скачивания', async () => {
  let opened = 0;
  const tg = {
    openLink: () => { opened += 1; },
    downloadFile: (params, callback) => {
      assert.equal(params.url, ACCESS.download_url);
      assert.equal(params.file_name, ACCESS.filename);
      callback(true);
    },
  };

  assert.equal(await openSignedDocument(ACCESS.download_url, ACCESS.filename, { telegram: tg }), true);
  assert.equal(opened, 0);
});

test('отказ Telegram downloadFile доходит как ошибка', async () => {
  const tg = { downloadFile: (_params, callback) => callback(false) };

  assert.equal(await openSignedDocument(ACCESS.download_url, ACCESS.filename, { telegram: tg }), false);
});

test('обычный браузер открывает подписанную ссылку напрямую', async () => {
  const opened = [];
  const result = await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: (url, target, features) => {
      opened.push([url, target, features]);
      return {};
    },
  });

  assert.equal(result, true);
  assert.deepEqual(opened, [[ACCESS.download_url, '_blank', 'noopener,noreferrer']]);
});

/*
 * Ссылка запрашивается у сервера, и только потом открывается окно. Между
 * нажатием и открытием проходит запрос, а браузер разрешает открывать окна
 * лишь «по нажатию»: Safari отзывает это разрешение сразу после ожидания,
 * Chrome — через несколько секунд. На медленной связи `window.open` возвращает
 * null, и пользователь получал ошибку вместо документа.
 *
 * Ответ сервера — вложение (Content-Disposition: attachment), поэтому его
 * можно забрать скрытой рамкой: она не всплывающее окно, её не блокируют, а
 * страница Mini App остаётся на месте. Рамка — запасной путь, а не основной:
 * открытая вкладка показывает ошибку сервера, если ссылка успела истечь.
 */
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

test('заблокированное окно не отменяет скачивание', async () => {
  const doc = fakeDocument();

  const result = await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => null,
    documentRef: doc,
  });

  assert.equal(result, true);
  assert.equal(doc.created.length, 1, 'скрытая рамка для скачивания не создана');
  assert.equal(doc.created[0].tag, 'iframe');
  assert.equal(doc.created[0].src, ACCESS.download_url);
  assert.deepEqual(doc.body.children, doc.created, 'рамка не добавлена на страницу');
});

test('открытое окно не дублируется скрытой рамкой', async () => {
  const doc = fakeDocument();

  await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => ({}),
    documentRef: doc,
  });

  assert.deepEqual(doc.created, [], 'документ скачивается дважды: окном и рамкой');
});

test('без страницы и без окна доставка честно проваливается', async () => {
  const result = await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => null,
    documentRef: null,
  });

  assert.equal(result, false, 'неудача выдаётся за скачивание');
});

test('бот не может написать первым — пользователь узнаёт, что делать', async () => {
  /*
   * Бэкенд отвечает 409 с готовой инструкцией: открыть бота и нажать «Старт».
   * Это чинится одним действием пользователя, поэтому подменять сообщение
   * подписанной ссылкой нельзя — оно должно дойти.
   */
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: true,
      openUrl: () => {},
      api: {
        sendDocumentToTelegram: async () => {
          throw httpError(409, 'Откройте бота KORGAN в Telegram и нажмите «Старт», затем повторите отправку.');
        },
        documentAccess: async () => ACCESS,
      },
    }),
    /нажмите «Старт»/,
  );
});

test('документа ещё нет — это ошибка, а не тихий успех', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      openUrl: () => {},
      api: {
        sendDocumentToTelegram: async () => ({ ok: true }),
        documentAccess: async () => {
          throw httpError(404, 'Документ по этому делу ещё не готов');
        },
      },
    }),
    /ещё не готов/,
  );
});

test('ответ без ссылки не выдаётся за выданный документ', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: false,
      openUrl: () => {},
      api: {
        sendDocumentToTelegram: async () => ({ ok: true }),
        documentAccess: async () => ({ ok: true, filename: 'KORGAN_claim.docx' }),
      },
    }),
    /ссылк/i,
  );
});

test('дело без идентификатора не отправляется в сеть', async () => {
  let calls = 0;
  await assert.rejects(
    deliverDocument('', {
      insideTelegram: false,
      openUrl: () => {},
      api: {
        sendDocumentToTelegram: async () => { calls += 1; },
        documentAccess: async () => { calls += 1; },
      },
    }),
  );
  assert.equal(calls, 0);
});

test('приложение больше не собирает файл из base64 в браузере', () => {
  // Путь blob + <a download> в Telegram WebView проваливается молча, поэтому
  // его не должно остаться ни в одном модуле.
  const code = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.ok(!/createObjectURL/.test(code), 'main.jsx всё ещё собирает blob для скачивания');
  assert.ok(!/downloadBase64/.test(code), 'main.jsx всё ещё скачивает документ из base64');
});

test('пользовательский путь вызывает оба серверных способа доставки', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.match(api, /\/document\/access/);
  assert.match(api, /\/document\/telegram/);
  assert.match(app, /deliverDocument\(activeCase\.id/);
});
