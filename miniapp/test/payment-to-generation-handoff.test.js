/**
 * Подтверждённая оплата сама уводит экран с оплаты на подготовку документа.
 *
 * Человек уходит платить во внешнее приложение и возвращается в Telegram.
 * К этому моменту оплата уже подтверждена провайдером, а подготовка документа
 * идёт на сервере — но экран продолжал показывать прежнюю кнопку «Провести
 * оплату», потому что состояние платежа обновлялось, а экран нет.
 *
 * Проверяется ровно это: подтверждение оплаты — событие сервера, и клиент
 * обязан на него отреагировать переходом, а не ждать нажатия.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isConfirmedDocumentPayment } from '../src/documentPaymentPolling.js';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('подтверждённая оплата распознаётся по состоянию заказа', () => {
  assert.equal(isConfirmedDocumentPayment({ status: 'approved' }), true);
  assert.equal(isConfirmedDocumentPayment({ status: 'consumed' }), true);
});

test('неподтверждённая оплата не считается подтверждённой', () => {
  for (const status of ['pending_receipt', 'awaiting_admin', 'cancelled', '']) {
    assert.equal(isConfirmedDocumentPayment({ status }), false, `статус ${status}`);
  }
  assert.equal(isConfirmedDocumentPayment(null), false);
});

test('опрос оплаты уводит экран на подготовку, как только оплата подтверждена', () => {
  const start = app.indexOf('startDocumentPaymentPolling({');
  const effect = app.slice(start, start + 700);

  assert.match(effect, /isConfirmedDocumentPayment/, 'опрос оплаты не реагирует на подтверждение');
  assert.match(effect, /syncCaseGeneration|applyGenerationState/, 'подтверждение оплаты не открывает подготовку');
});

test('ответ на чек с задачей открывает подготовку, а не остаётся на экране оплаты', () => {
  const start = app.indexOf('const uploadDocReceipt');
  const handler = app.slice(start, app.indexOf('const refreshDocPayment'));

  assert.match(handler, /applyGenerationState/, 'подтверждённый чек не открывает экран подготовки');
  assert.match(handler, /result\??\.job/, 'ответ о запущенной задаче не распознаётся');
});

test('возврат в Mini App синхронизирует состояние с сервером', () => {
  assert.match(app, /visibilitychange/, 'возврат из внешнего приложения не синхронизирует состояние');

  const start = app.indexOf("addEventListener('visibilitychange'");
  const effect = app.slice(Math.max(0, start - 700), start + 700);
  assert.match(effect, /removeEventListener\('visibilitychange'/, 'подписка на возврат не снимается');
  assert.match(effect, /doc-payment|generating/, 'возврат синхронизирует не те экраны');
});
