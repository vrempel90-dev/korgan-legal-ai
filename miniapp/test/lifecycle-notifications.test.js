import test from 'node:test';
import assert from 'node:assert/strict';

import {
  clearLifecycleNotificationData,
  createLifecycleNotificationLedger,
  generationEvent,
  lifecycleNotificationCopy,
} from '../src/lifecycleNotifications.js';

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}

test('один case/job/status можно заявить только один раз', () => {
  const storage = memoryStorage();
  const ledger = createLifecycleNotificationLedger({ storage, now: () => 100 });
  const event = { caseId: 'case-1', jobId: 'job-1', eventType: 'running' };

  assert.equal(ledger.claim(event), true);
  assert.equal(ledger.claim(event), false);
});

test('reopen читает тот же ledger и не повторяет уже показанное событие', () => {
  const storage = memoryStorage();
  const first = createLifecycleNotificationLedger({ storage, now: () => 100 });
  assert.equal(first.claim({ caseId: 'case-1', jobId: 'job-1', eventType: 'ready' }), true);

  const reopened = createLifecycleNotificationLedger({ storage, now: () => 200 });
  assert.equal(reopened.claim({ caseId: 'case-1', jobId: 'job-1', eventType: 'ready' }), false);
});

test('глобальное удаление данных стирает ledger уведомлений', () => {
  const storage = memoryStorage();
  const first = createLifecycleNotificationLedger({ storage, now: () => 100 });
  assert.equal(first.claim({ caseId: 'case-1', jobId: 'job-1', eventType: 'ready' }), true);

  clearLifecycleNotificationData(storage);

  const afterDelete = createLifecycleNotificationLedger({ storage, now: () => 200 });
  assert.equal(afterDelete.claim({ caseId: 'case-1', jobId: 'job-1', eventType: 'ready' }), true);
});

test('второе дело не наследует уведомление первого', () => {
  const storage = memoryStorage();
  const ledger = createLifecycleNotificationLedger({ storage });

  assert.equal(ledger.claim({ caseId: 'case-1', jobId: 'job-1', eventType: 'ready' }), true);
  assert.equal(ledger.claim({ caseId: 'case-2', jobId: 'job-1', eventType: 'ready' }), true);
});

test('READY event невозможен без сохранённого filename', () => {
  const job = { caseId: 'case-1', jobId: 'job-1', status: 'succeeded' };
  assert.equal(generationEvent(job, null), null);
  assert.equal(generationEvent(job, { status: 'document_ready' }), null);
  assert.equal(generationEvent(job, { status: 'document_ready', filename: 'claim.docx' }), 'ready');
});

test('polling running даёт стабильный тип события, дедупликацией занимается ledger', () => {
  const job = { caseId: 'case-1', jobId: 'job-1', status: 'running' };
  assert.equal(generationEvent(job), 'running');
  assert.equal(generationEvent(job), 'running');
});

test('клиентские тексты не содержат технических названий', () => {
  assert.equal(lifecycleNotificationCopy('ready', 'ru'), 'Документ готов');
  assert.equal(lifecycleNotificationCopy('failed', 'ru'), 'Не удалось подготовить документ');
  assert.equal(lifecycleNotificationCopy('ready', 'kk'), 'Құжат дайын');
});
