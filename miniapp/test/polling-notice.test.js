/**
 * Сбой опроса живёт до следующего ответа, а не до конца экрана.
 *
 * Опрос подготовки документа и опрос решения по оплате писали свою ошибку тем
 * же сообщением экрана, что и действия пользователя, и никогда её не убирали.
 * Связь восстанавливалась, прогресс снова шёл, статус оплаты снова читался — а
 * над кнопками продолжала висеть строка «Сервис временно недоступен».
 * Уведомление противоречило тому, что происходит на том же экране, и гасло
 * только при смене экрана.
 *
 * Обратное лечение — стирать сообщение на каждом удачном ответе — стёрло бы и
 * чужое: на экране оплаты живёт ответ о принятом чеке, и опрос не вправе его
 * снимать. Поэтому опрос убирает ровно то, что написал сам.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { pollingNoticeUpdate } from '../src/pollingNotice.js';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('на пустом экране сообщение опроса показывается', () => {
  assert.deepEqual(
    pollingNoticeUpdate({ shown: '', owned: '', text: 'Сервис временно недоступен' }),
    { shown: 'Сервис временно недоступен', owned: 'Сервис временно недоступен' },
  );
});

test('следующий удачный ответ убирает сообщение опроса', () => {
  const failed = pollingNoticeUpdate({ shown: '', owned: '', text: 'Сервис временно недоступен' });

  assert.deepEqual(
    pollingNoticeUpdate({ shown: failed.shown, owned: failed.owned, text: '' }),
    { shown: '', owned: '' },
  );
});

test('опрос не затирает сообщение, написанное действием пользователя', () => {
  const update = pollingNoticeUpdate({
    shown: 'Чек прошёл предварительную проверку.',
    owned: '',
    text: 'Сервис временно недоступен',
  });

  assert.equal(update.shown, 'Чек прошёл предварительную проверку.');
});

test('удачный ответ не снимает сообщение действия пользователя', () => {
  const blocked = pollingNoticeUpdate({
    shown: 'Чек прошёл предварительную проверку.',
    owned: '',
    text: 'Сервис временно недоступен',
  });

  assert.equal(
    pollingNoticeUpdate({ shown: blocked.shown, owned: blocked.owned, text: '' }).shown,
    'Чек прошёл предварительную проверку.',
  );
});

test('повторный сбой не меняет показанного сообщения', () => {
  const first = pollingNoticeUpdate({ shown: '', owned: '', text: 'Сервис временно недоступен' });
  const second = pollingNoticeUpdate({ shown: first.shown, owned: first.owned, text: 'Сервис временно недоступен' });

  assert.deepEqual(second, first);
});

test('опросы подготовки и оплаты сообщают о сбое через собственное сообщение', () => {
  assert.doesNotMatch(
    app,
    /onError: error => setNotice\(clientMessage\(error\)\)/,
    'сбой опроса пишется как обычное уведомление и уже не убирается',
  );
  const calls = [...app.matchAll(/reportPolling/g)];
  assert.ok(calls.length >= 5, `опросы должны сообщать о сбое и о восстановлении, найдено ${calls.length}`);
});
