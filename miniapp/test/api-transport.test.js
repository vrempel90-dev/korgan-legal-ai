/**
 * Сетевой слой Mini App обязан отличать отказ сети, таймаут и испорченный ответ.
 * Повторять можно только безопасные чтения: повтор POST способен создать второе
 * дело, второй заказ или повторно запустить генерацию.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createApiTransport } from '../src/apiTransport.js';

const miniapp = join(dirname(fileURLToPath(import.meta.url)), '..');

function response({ status = 200, contentType = 'application/json', body = '{}' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: name => name.toLowerCase() === 'content-type' ? contentType : null },
    text: async () => body,
  };
}

function transport(fetchImpl, overrides = {}) {
  return createApiTransport({
    baseUrl: 'https://api.korgan.test',
    getTelegramInitData: () => 'signed-init-data',
    fetchImpl,
    retryDelay: async () => {},
    ...overrides,
  });
}

test('подписанные данные Telegram и JSON-заголовок доходят до API', async () => {
  const calls = [];
  const request = transport(async (...args) => {
    calls.push(args);
    return response({ body: '{"ok":true}' });
  });

  const result = await request('/miniapp/cases', {
    method: 'POST',
    body: JSON.stringify({ description: 'Факты' }),
  });

  assert.deepEqual(result, { ok: true });
  assert.equal(calls[0][0], 'https://api.korgan.test/miniapp/cases');
  assert.equal(calls[0][1].headers['X-Telegram-Init-Data'], 'signed-init-data');
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json');
});

test('повреждённый JSON успешного ответа не превращается в пустой объект', async () => {
  const request = transport(async () => response({ body: '{broken' }));

  await assert.rejects(request('/health'), error => {
    assert.equal(error.code, 'KORGAN_API_INVALID_RESPONSE');
    assert.match(error.message, /некорректный ответ/i);
    return true;
  });
});

test('JSON-ошибка API сохраняет HTTP-статус и detail', async () => {
  const request = transport(async () => response({
    status: 409,
    body: '{"detail":"Нажмите «Старт» и повторите"}',
  }));

  await assert.rejects(request('/miniapp/document/telegram', { method: 'POST' }), error => {
    assert.equal(error.status, 409);
    assert.equal(error.message, 'Нажмите «Старт» и повторите');
    assert.deepEqual(error.payload, { detail: 'Нажмите «Старт» и повторите' });
    return true;
  });
});

test('сетевой отказ GET повторяется один раз и затем проходит', async () => {
  let calls = 0;
  const request = transport(async () => {
    calls += 1;
    if (calls === 1) throw new TypeError('Failed to fetch');
    return response({ body: '{"status":"ok"}' });
  });

  assert.deepEqual(await request('/health'), { status: 'ok' });
  assert.equal(calls, 2);
});

test('временный 503 на GET повторяется один раз', async () => {
  let calls = 0;
  const request = transport(async () => {
    calls += 1;
    return calls === 1
      ? response({ status: 503, body: '{"detail":"Перезапуск"}' })
      : response({ body: '{"status":"ok"}' });
  });

  assert.deepEqual(await request('/health'), { status: 'ok' });
  assert.equal(calls, 2);
});

test('POST не повторяется после сетевого отказа', async () => {
  let calls = 0;
  const request = transport(async () => {
    calls += 1;
    throw new TypeError('Failed to fetch');
  });

  await assert.rejects(
    request('/miniapp/documents/generate', { method: 'POST', body: '{}' }),
    error => error.code === 'KORGAN_API_NETWORK_ERROR',
  );
  assert.equal(calls, 1);
});

test('зависший запрос прерывается по таймауту с отдельной ошибкой', async () => {
  let calls = 0;
  const request = transport((_url, options) => {
    calls += 1;
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    });
  }, { timeoutMs: 5, maxGetRetries: 0 });

  await assert.rejects(request('/health'), error => {
    assert.equal(error.code, 'KORGAN_API_TIMEOUT');
    assert.match(error.message, /время ожидания/i);
    return true;
  });
  assert.equal(calls, 1);
});

test('индивидуальный таймаут управляет долгой генерацией', async () => {
  let aborted = false;
  const request = transport((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      aborted = true;
      reject(new DOMException('Aborted', 'AbortError'));
    });
  }), { timeoutMs: 1000, maxGetRetries: 0 });

  await assert.rejects(
    request('/miniapp/documents/generate', { method: 'POST', timeoutMs: 5 }),
    error => error.code === 'KORGAN_API_TIMEOUT',
  );
  assert.equal(aborted, true);
});

test('боевой API использует единый транспорт, а не собственный fetch', () => {
  const source = readFileSync(join(miniapp, 'src', 'korganApi.js'), 'utf8');
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');

  assert.match(clean, /createApiTransport/);
  assert.doesNotMatch(clean, /await\s+fetch\s*\(/);
});
