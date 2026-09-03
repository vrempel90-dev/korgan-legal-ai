/**
 * Готовый документ должен выдаваться только внутри Mini App по подписанной
 * HTTPS-ссылке. Telegram-бот не является запасным или основным каналом.
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

test('внутри Telegram документ остаётся в Mini App и не отправляется ботом', async () => {
  const opened = [];
  let accessCalls = 0;
  const result = await deliverDocument('KOR-1', {
    insideTelegram: true,
    openUrl: (url) => { opened.push(url); return true; },
    api: {
      documentAccess: async () => { accessCalls += 1; return ACCESS; },
    },
  });

  assert.equal(result.via, 'link');
  assert.equal(result.filename, ACCESS.filename);
  assert.equal(accessCalls, 1);
  assert.deepEqual(opened, [ACCESS.download_url]);
});

test('обычный браузер использует тот же подписанный URL', async () => {
  const opened = [];
  const result = await deliverDocument('KOR-1', {
    insideTelegram: false,
    openUrl: (url) => { opened.push(url); return true; },
    api: { documentAccess: async () => ACCESS },
  });

  assert.equal(result.via, 'link');
  assert.deepEqual(opened, [ACCESS.download_url]);
});

test('заблокированное открытие ссылки считается ошибкой доставки', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: true,
      openUrl: () => false,
      api: { documentAccess: async () => ACCESS },
    }),
    /открыть/i,
  );
});

test('Telegram downloadFile используется только как нативный механизм скачивания URL', async () => {
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

test('отказ native downloadFile честно считается отказом', async () => {
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

test('заблокированное окно использует скрытую рамку', async () => {
  const doc = fakeDocument();
  const result = await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => null,
    documentRef: doc,
  });

  assert.equal(result, true);
  assert.equal(doc.created.length, 1);
  assert.equal(doc.created[0].tag, 'iframe');
  assert.equal(doc.created[0].src, ACCESS.download_url);
});

test('открытое окно не дублируется скрытой рамкой', async () => {
  const doc = fakeDocument();
  await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => ({}),
    documentRef: doc,
  });
  assert.deepEqual(doc.created, []);
});

test('без страницы и без окна доставка честно проваливается', async () => {
  const result = await openSignedDocument(ACCESS.download_url, ACCESS.filename, {
    telegram: null,
    openWindow: () => null,
    documentRef: null,
  });
  assert.equal(result, false);
});

test('документа ещё нет — это ошибка, а не тихий успех', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: true,
      openUrl: () => true,
      api: {
        documentAccess: async () => { throw httpError(404, 'Документ ещё не готов'); },
      },
    }),
    /ещё не готов/,
  );
});

test('ответ без ссылки не выдаётся за выданный документ', async () => {
  await assert.rejects(
    deliverDocument('KOR-1', {
      insideTelegram: true,
      openUrl: () => true,
      api: { documentAccess: async () => ({ ok: true, filename: ACCESS.filename }) },
    }),
    /ссылк/i,
  );
});

test('дело без идентификатора не отправляется в сеть', async () => {
  let calls = 0;
  await assert.rejects(
    deliverDocument('', {
      insideTelegram: true,
      openUrl: () => true,
      api: { documentAccess: async () => { calls += 1; } },
    }),
  );
  assert.equal(calls, 0);
});

test('клиентский API не содержит маршрута отправки документа ботом', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');
  const delivery = readFileSync(join(src, 'documentDelivery.js'), 'utf8');
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.match(api, /\/document\/access/);
  assert.doesNotMatch(api, /\/document\/telegram/);
  assert.doesNotMatch(api, /sendDocumentToTelegram/);
  assert.doesNotMatch(delivery, /delivered_to\s*!==\s*['"]telegram['"]/);
  assert.match(app, /deliverDocument\(activeCase\.id/);
});

test('приложение не собирает Word из base64 в браузере', () => {
  const code = readFileSync(join(src, 'main.jsx'), 'utf8');
  assert.ok(!/createObjectURL/.test(code));
  assert.ok(!/downloadBase64/.test(code));
});
