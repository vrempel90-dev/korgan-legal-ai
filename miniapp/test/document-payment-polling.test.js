/**
 * Фоновая проверка оплаты не должна молчать, пересекаться сама с собой или
 * обновлять уже закрытый экран. Tole остаётся в polling до server-side
 * подтверждения, legacy Kaspi сохраняет прежнюю ручную семантику.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  isAutomaticDocumentPayment,
  requireDocumentPayment,
  shouldPollDocumentPayment,
  startDocumentPaymentPolling,
} from '../src/documentPaymentPolling.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

function scheduler() {
  const jobs = new Map();
  let nextId = 1;
  return {
    jobs,
    schedule(callback, delay) {
      const id = nextId;
      nextId += 1;
      jobs.set(id, { callback, delay });
      return id;
    },
    cancel(id) {
      jobs.delete(id);
    },
    async runNext() {
      const [id, job] = jobs.entries().next().value || [];
      assert.ok(job, 'ожидался запланированный опрос');
      jobs.delete(id);
      await job.callback();
    },
  };
}

function pollingOptions(overrides = {}) {
  const clock = overrides.clock || scheduler();
  return {
    orderId: 'DOC-42',
    fetchStatus: async () => ({ payment: { order_id: 'DOC-42', status: 'awaiting_admin' } }),
    onPayment: () => {},
    onError: () => {},
    intervalMs: 8000,
    schedule: clock.schedule.bind(clock),
    cancelSchedule: clock.cancel.bind(clock),
    ...overrides,
    clock,
  };
}

test('первый опрос планируется с заданным интервалом', () => {
  const options = pollingOptions();
  const stop = startDocumentPaymentPolling(options);

  assert.equal(options.clock.jobs.size, 1);
  assert.equal([...options.clock.jobs.values()][0].delay, 8000);
  stop();
});

test('подтверждённый статус доезжает до интерфейса и завершает опрос', async () => {
  const payments = [];
  const options = pollingOptions({
    fetchStatus: async () => ({ payment: { order_id: 'DOC-42', status: 'approved' } }),
    onPayment: payment => payments.push(payment),
  });
  startDocumentPaymentPolling(options);

  await options.clock.runNext();

  assert.deepEqual(payments, [{ order_id: 'DOC-42', status: 'approved' }]);
  assert.equal(options.clock.jobs.size, 0);
});

test('Tole pending_receipt продолжает опрашиваться до автоматического подтверждения', async () => {
  const payments = [];
  const options = pollingOptions({
    fetchStatus: async () => ({
      payment: {
        order_id: 'DOC-42',
        status: 'pending_receipt',
        payment_provider: 'tole',
        automatic_confirmation: true,
        payment_url: 'https://pay.tole.example/42',
      },
    }),
    onPayment: payment => payments.push(payment),
  });
  startDocumentPaymentPolling(options);

  await options.clock.runNext();

  assert.equal(payments.length, 1);
  assert.equal(options.clock.jobs.size, 1, 'Tole polling остановился до подтверждения оплаты');
});

test('Tole approved завершает polling', async () => {
  const options = pollingOptions({
    fetchStatus: async () => ({
      payment: {
        order_id: 'DOC-42',
        status: 'approved',
        payment_provider: 'tole',
        automatic_confirmation: true,
      },
    }),
  });
  startDocumentPaymentPolling(options);

  await options.clock.runNext();

  assert.equal(options.clock.jobs.size, 0);
});

test('автоматический провайдер определяется без зависимости от названия статуса', () => {
  assert.equal(isAutomaticDocumentPayment({ payment_provider: 'tole' }), true);
  assert.equal(isAutomaticDocumentPayment({ automatic_confirmation: true }), true);
  assert.equal(isAutomaticDocumentPayment({ payment_provider: 'kaspi-manual' }), false);
  assert.equal(shouldPollDocumentPayment({ status: 'pending_receipt', payment_provider: 'tole' }), true);
  assert.equal(shouldPollDocumentPayment({ status: 'pending_receipt' }), false);
  assert.equal(shouldPollDocumentPayment({ status: 'awaiting_admin' }), true);
  assert.equal(shouldPollDocumentPayment({ status: 'cancelled', payment_provider: 'tole' }), false);
});

test('сетевая ошибка показывается и следующий опрос всё равно планируется', async () => {
  const errors = [];
  const options = pollingOptions({
    fetchStatus: async () => { throw new Error('Telegram API недоступен'); },
    onError: error => errors.push(error.message),
  });
  startDocumentPaymentPolling(options);

  await options.clock.runNext();

  assert.deepEqual(errors, ['Telegram API недоступен']);
  assert.equal(options.clock.jobs.size, 1);
});

test('неполный успешный ответ не считается статусом оплаты', async () => {
  const errors = [];
  const options = pollingOptions({
    fetchStatus: async () => ({ ok: true }),
    onError: error => errors.push(error.message),
  });
  startDocumentPaymentPolling(options);

  await options.clock.runNext();

  assert.match(errors[0], /неполный статус оплаты/i);
  assert.equal(options.clock.jobs.size, 1);
});

test('следующий таймер появляется только после завершения запроса', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const options = pollingOptions({ fetchStatus: () => pending });
  startDocumentPaymentPolling(options);

  const [id, job] = options.clock.jobs.entries().next().value;
  options.clock.jobs.delete(id);
  const running = job.callback();
  assert.equal(options.clock.jobs.size, 0);

  release({ payment: { order_id: 'DOC-42', status: 'awaiting_admin' } });
  await running;
  assert.equal(options.clock.jobs.size, 1);
});

test('неполный ответ об оплате отвергается одним общим правилом', () => {
  const payment = { order_id: 'DOC-42', status: 'awaiting_admin' };

  assert.deepEqual(requireDocumentPayment({ payment }), payment);
  assert.throws(() => requireDocumentPayment({ ok: true }), /неполный статус оплаты/i);
  assert.throws(() => requireDocumentPayment(null), /неполный статус оплаты/i);
  assert.throws(() => requireDocumentPayment({ payment: { order_id: 'DOC-42' } }), /неполный статус оплаты/i);
});

test('ручное обновление оплаты и загрузка чека проверяют ответ так же', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  const unchecked = app.match(/setDocPayment\(result\.payment\)/g) || [];

  assert.match(app, /requireDocumentPayment\(/, 'ответы об оплате принимаются на веру');
  assert.deepEqual(unchecked, [], 'ответ об оплате попадает в состояние без проверки');
});

test('остановка удаляет ожидающий таймер', () => {
  let calls = 0;
  const options = pollingOptions({ fetchStatus: async () => { calls += 1; } });
  const stop = startDocumentPaymentPolling(options);

  stop();

  assert.equal(options.clock.jobs.size, 0);
  assert.equal(calls, 0);
});

test('ответ завершившегося экрана не меняет состояние и не запускает новый таймер', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const payments = [];
  const errors = [];
  const options = pollingOptions({
    fetchStatus: () => pending,
    onPayment: payment => payments.push(payment),
    onError: error => errors.push(error),
  });
  const stop = startDocumentPaymentPolling(options);

  const [id, job] = options.clock.jobs.entries().next().value;
  options.clock.jobs.delete(id);
  const running = job.callback();
  stop();
  release({ payment: { order_id: 'DOC-42', status: 'approved' } });
  await running;

  assert.deepEqual(payments, []);
  assert.deepEqual(errors, []);
  assert.equal(options.clock.jobs.size, 0);
});
