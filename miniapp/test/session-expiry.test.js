/**
 * Просроченная подпись Telegram объясняется человеку, а не показывается кодом.
 *
 * Ошибки из API попадали на экран как есть: `setNotice(error?.message || t.down)`.
 * Для протухшего initData сервер отдаёт «Telegram authentication expired», и
 * клиент видел английскую служебную строку, из которой не следует ни причина,
 * ни действие: повторное нажатие не помогает, подпись обновляется только при
 * повторном открытии Mini App.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const app = readFileSync(join(src, 'main.jsx'), 'utf8');

test('обе языковые версии объясняют просроченную сессию', () => {
  const messages = app.match(/sessionExpired: '([^']+)'/g) || [];

  assert.equal(messages.length, 2, 'объяснение просроченной сессии есть не на всех языках');
  for (const message of messages) {
    assert.ok(
      /(зан|қайта|заново|ашы)/i.test(message),
      `сообщение не говорит, что Mini App нужно открыть заново: ${message}`,
    );
  }
});

test('ни один обработчик не показывает служебный текст сервера напрямую', () => {
  const raw = app.match(/setNotice\(error\?\.message \|\| t\.down\)/g) || [];

  assert.deepEqual(raw, [], 'ответ сервера попадает на экран без разбора');
  assert.match(app, /const clientMessage = /, 'нет общего правила показа ошибки клиенту');
});

test('просроченная сессия распознаётся по коду, а не по тексту ошибки', () => {
  const rule = app.slice(app.indexOf('const clientMessage = '), app.indexOf('const showScreen'));

  assert.match(rule, /KORGAN_API_UNAUTHORIZED/, 'просроченная сессия отличается только по тексту сервера');
  assert.match(rule, /t\.sessionExpired/, 'просроченная сессия объясняется тем же служебным текстом');
  assert.match(rule, /t\.down/, 'ошибка без объяснения остаётся без запасного текста');
});
