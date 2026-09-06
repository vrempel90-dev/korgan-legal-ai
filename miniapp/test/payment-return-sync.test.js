import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isConfirmedDocumentPayment,
  shouldPollDocumentPayment,
  startDocumentPaymentPolling,
} from '../src/documentPaymentPolling.js';

function scheduler() {
  const jobs = new Map();
  let nextId = 1;
  return {
    jobs,
    schedule(callback, delay) {
      const id = nextId++;
      jobs.set(id, { callback, delay });
      return id;
    },
    cancel(id) { jobs.delete(id); },
    async runNext() {
      const [id, job] = jobs.entries().next().value || [];
      assert.ok(job, 'ожидался polling timer');
      jobs.delete(id);
      await job.callback();
    },
  };
}

function visibilityTarget() {
  const listeners = new Set();
  return {
    hidden: false,
    addEventListener(name, callback) {
      if (name === 'visibilitychange') listeners.add(callback);
    },
    removeEventListener(name, callback) {
      if (name === 'visibilitychange') listeners.delete(callback);
    },
    fire() { for (const callback of [...listeners]) callback(); },
    listenerCount() { return listeners.size; },
  };
}

test('manual approved остаётся в polling до появления durable generation job', async () => {
  assert.equal(isConfirmedDocumentPayment({ status: 'approved' }), true);
  assert.equal(shouldPollDocumentPayment({ status: 'approved' }), true);
  assert.equal(shouldPollDocumentPayment({ status: 'consumed' }), true);

  const clock = scheduler();
  let reads = 0;
  const generations = [];
  const payment = { order_id: '77', case_id: 'case-77', status: 'approved' };

  startDocumentPaymentPolling({
    orderId: '77',
    fetchStatus: async () => {
      reads += 1;
      if (reads === 1) return { payment };
      return {
        payment,
        job: { job_id: 'job-77', case_id: 'case-77', status: 'running', stage: 'legal_research', progress: 42 },
      };
    },
    onPayment: () => {},
    onGeneration: result => generations.push(result.job),
    onError: error => { throw error; },
    schedule: clock.schedule.bind(clock),
    cancelSchedule: clock.cancel.bind(clock),
  });

  await clock.runNext();
  assert.equal(clock.jobs.size, 1, 'approved без job не должен оставлять старый экран оплаты навсегда');

  await clock.runNext();
  assert.equal(generations.length, 1);
  assert.equal(generations[0].job_id, 'job-77');
  assert.equal(clock.jobs.size, 0, 'после получения job polling оплаты должен остановиться');
});

test('возврат из банковского приложения делает немедленную сверку без второго параллельного запроса', async () => {
  const clock = scheduler();
  const visibility = visibilityTarget();
  let release;
  let calls = 0;
  const first = new Promise(resolve => { release = resolve; });

  const stop = startDocumentPaymentPolling({
    orderId: '88',
    fetchStatus: async () => {
      calls += 1;
      if (calls === 1) return first;
      return {
        payment: { order_id: '88', case_id: 'case-88', status: 'approved' },
        job: { job_id: 'job-88', case_id: 'case-88', status: 'running', stage: 'legal_research', progress: 20 },
      };
    },
    onPayment: () => {},
    onGeneration: () => {},
    onError: error => { throw error; },
    schedule: clock.schedule.bind(clock),
    cancelSchedule: clock.cancel.bind(clock),
    visibilityTarget: visibility,
    immediate: true,
  });

  assert.equal(calls, 1);
  visibility.fire();
  assert.equal(calls, 1, 'visibilitychange не должен создавать второй in-flight status request');

  release({ payment: { order_id: '88', case_id: 'case-88', status: 'approved' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(clock.jobs.size, 1, 'после approved без job должен быть запланирован повтор');

  visibility.fire();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2, 'возврат должен отменить ожидание таймера и проверить статус сразу');
  assert.equal(clock.jobs.size, 0);

  stop();
  assert.equal(visibility.listenerCount(), 0, 'cleanup обязан снять visibility listener');
});
