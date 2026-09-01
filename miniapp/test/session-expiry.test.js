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
const rule = readFileSync(join(src, 'clientMessage.js'), 'utf8');

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
  // Правило одно на всё приложение, поэтому и проверка одна: текст ошибки
  // читается ровно в одном месте — там, где решается, что показать человеку,
  // и это место больше не экран, а отдельный модуль.
  assert.equal(
    (app.match(/error\?\.message/g) || []).length,
    0,
    'ответ сервера попадает на экран без разбора',
  );
  assert.equal(
    (rule.match(/error\?\.message/g) || []).length,
    1,
    'текст ошибки читается не только в общем правиле',
  );
  assert.match(app, /const clientMessage = /, 'нет общего правила показа ошибки клиенту');
});

test('сбой ответа в чате не выдаётся за реплику юриста', () => {
  /*
   * Ошибка запроса добавлялась в переписку как сообщение от ИИ. При протухшей
   * подписи Telegram в диалоге появлялось «Telegram authentication expired» —
   * английская служебная строка от лица консультанта, из которой не следует ни
   * причина, ни то, что помогает повторное открытие Mini App.
   */
  const send = app.slice(app.indexOf('const sendMessage'), app.indexOf('const uploadConsultReceipt'));

  assert.match(send, /clientMessage\(error\)/, 'чат показывает ответ сервера как есть');
  assert.doesNotMatch(send, /error\?\.message/, 'чат читает текст ошибки в обход общего правила');
});

test('просроченная сессия распознаётся по коду, а не по тексту ошибки', () => {
  assert.match(rule, /KORGAN_API_UNAUTHORIZED/, 'просроченная сессия отличается только по тексту сервера');
  assert.match(rule, /texts\.sessionExpired/, 'просроченная сессия объясняется тем же служебным текстом');
  assert.match(rule, /texts\.down/, 'ошибка без объяснения остаётся без запасного текста');
});
