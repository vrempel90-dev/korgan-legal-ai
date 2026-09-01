/**
 * Подготовка документа перестала помещаться в один HTTP-запрос, и клиент обязан
 * читать состояние задачи с сервера.
 *
 * До этого приложение ждало готовый документ прямо в ответе на запуск и любой
 * другой ответ считало поломкой выпуска. После переноса работы в сохраняемую
 * задачу сервер отвечает описанием задачи — и генерация в Mini App падала с
 * сообщением о неполных данных выпуска.
 *
 * Здесь проверяется противоположное свойство: клиент ничего не досочиняет.
 * Проценты приходят с сервера, готовность объявляется только вместе с реально
 * сохранённым документом, а опрос не накладывается сам на себя.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { interpretGeneration, startGenerationPolling } from '../src/generationJob.js';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');

const RUNNING_JOB = {
  job_id: 'job-1',
  case_id: 'case-1',
  status: 'running',
  stage: 'legal_research',
  progress: 20,
  document_ready: false,
  retryable: false,
  error: '',
};

const READY_JOB = {
  ...RUNNING_JOB,
  status: 'succeeded',
  stage: 'completed',
  progress: 100,
  document_ready: true,
};

const DOCUMENT = {
  case_id: 'case-1',
  status: 'document_ready',
  title: 'Исковое заявление',
  filename: 'claim.docx',
  filing_ready: false,
  release_status: 'preliminary',
  verification_status: 'needs_verification',
  verification_notes: ['Проверить госпошлину'],
  quality_score: 8.4,
  quality_issues: ['Указать банковские реквизиты'],
};

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

test('запуск подготовки читается как принятая в работу задача, а не как поломка выпуска', () => {
  const state = interpretGeneration({
    payment_required: false,
    generation_started: true,
    job: RUNNING_JOB,
  });

  assert.equal(state.status, 'running');
  assert.equal(state.job.jobId, 'job-1');
  assert.equal(state.job.progress, 20);
  assert.equal(state.job.stage, 'legal_research');
  assert.equal(state.document, null);
});

test('требование оплаты остаётся требованием оплаты', () => {
  const state = interpretGeneration({
    payment_required: true,
    generation_started: false,
    payment: { order_id: 'DOC-42', status: 'pending_receipt', amount_kzt: 9900 },
  });

  assert.equal(state.status, 'payment_required');
  assert.equal(state.payment.order_id, 'DOC-42');
  assert.equal(state.job, null);
});

test('готовность объявляется только вместе с описанием сохранённого документа', () => {
  const state = interpretGeneration({
    payment_required: false,
    generation_started: false,
    job: READY_JOB,
    document: DOCUMENT,
  });

  assert.equal(state.status, 'ready');
  assert.equal(state.document.filename, 'claim.docx');
  assert.equal(state.document.release_status, 'preliminary');
});

test('успешная задача без документа не превращается в READY', () => {
  assert.throws(
    () => interpretGeneration({ payment_required: false, job: READY_JOB }),
    /документ/i,
  );
});

test('ответ без описания задачи отвергается, а не показывается как прогресс', () => {
  assert.throws(() => interpretGeneration({ payment_required: false }), /подготовк/i);
  assert.throws(
    () => interpretGeneration({ job: { job_id: 'job-1', status: 'running' } }),
    /подготовк/i,
  );
});

test('провал задачи отдаёт причину и признак повторного запуска без новой оплаты', () => {
  const state = interpretGeneration({
    payment_required: false,
    generation_started: false,
    job: {
      ...RUNNING_JOB,
      status: 'failed',
      stage: 'interrupted',
      progress: 0,
      retryable: true,
      error: 'Сервис перезапустился во время подготовки документа.',
    },
  });

  assert.equal(state.status, 'failed');
  assert.equal(state.job.retryable, true);
  assert.match(state.job.error, /перезапустил/);
});

test('дело без начатой подготовки читается как отсутствие задачи', () => {
  const state = interpretGeneration({ job: null });

  assert.equal(state.status, 'idle');
  assert.equal(state.job, null);
});

test('опрос планирует следующий запрос только после ответа на предыдущий', async () => {
  const clock = scheduler();
  let inFlight = 0;
  let overlaps = 0;

  const stop = startGenerationPolling({
    jobId: 'job-1',
    intervalMs: 2000,
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: async () => {
      inFlight += 1;
      if (inFlight > 1) overlaps += 1;
      await Promise.resolve();
      inFlight -= 1;
      return { job: RUNNING_JOB };
    },
    onProgress: () => {},
    onReady: () => {},
    onFailed: () => {},
    onError: () => {},
  });

  assert.equal(clock.jobs.size, 1);
  await clock.runNext();
  assert.equal(clock.jobs.size, 1, 'после ответа планируется ровно один следующий опрос');
  await clock.runNext();
  assert.equal(overlaps, 0);
  stop();
  assert.equal(clock.jobs.size, 0);
});

test('прогресс приходит с сервера и не досочиняется между опросами', async () => {
  const clock = scheduler();
  const seen = [];
  const answers = [
    { job: { ...RUNNING_JOB, stage: 'starting', progress: 5 } },
    { job: { ...RUNNING_JOB, stage: 'quality_control', progress: 80 } },
  ];

  startGenerationPolling({
    jobId: 'job-1',
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: async () => answers.shift(),
    onProgress: (job) => seen.push([job.stage, job.progress]),
    onReady: () => {},
    onFailed: () => {},
    onError: () => {},
  });

  await clock.runNext();
  await clock.runNext();

  assert.deepEqual(seen, [['starting', 5], ['quality_control', 80]]);
});

test('готовый документ объявляется один раз и останавливает опрос', async () => {
  const clock = scheduler();
  const ready = [];

  startGenerationPolling({
    jobId: 'job-1',
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: async () => ({ job: READY_JOB, document: DOCUMENT }),
    onProgress: () => {},
    onReady: (document, job) => ready.push([document.filename, job.progress]),
    onFailed: () => {},
    onError: () => {},
  });

  await clock.runNext();

  assert.deepEqual(ready, [['claim.docx', 100]]);
  assert.equal(clock.jobs.size, 0, 'после готовности опрос не продолжается');
});

test('провал объявляется один раз и останавливает опрос', async () => {
  const clock = scheduler();
  const failures = [];

  startGenerationPolling({
    jobId: 'job-1',
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: async () => ({
      job: { ...RUNNING_JOB, status: 'failed', retryable: true, error: 'Провайдер недоступен' },
    }),
    onProgress: () => {},
    onReady: () => {},
    onFailed: (job) => failures.push(job.error),
    onError: () => {},
  });

  await clock.runNext();

  assert.deepEqual(failures, ['Провайдер недоступен']);
  assert.equal(clock.jobs.size, 0);
});

test('временная сетевая ошибка не выдаётся за провал подготовки', async () => {
  const clock = scheduler();
  const errors = [];
  const failures = [];
  let attempt = 0;

  startGenerationPolling({
    jobId: 'job-1',
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: async () => {
      attempt += 1;
      if (attempt === 1) throw new Error('Failed to fetch');
      return { job: READY_JOB, document: DOCUMENT };
    },
    onProgress: () => {},
    onReady: () => {},
    onFailed: (job) => failures.push(job),
    onError: (error) => errors.push(error.message),
  });

  await clock.runNext();
  assert.deepEqual(errors, ['Failed to fetch']);
  assert.deepEqual(failures, []);
  assert.equal(clock.jobs.size, 1, 'после сетевой ошибки опрос продолжается');

  await clock.runNext();
  assert.equal(clock.jobs.size, 0);
});

test('остановленный опрос молчит даже при уже начатом запросе', async () => {
  const clock = scheduler();
  const events = [];
  let release = null;

  const stop = startGenerationPolling({
    jobId: 'job-1',
    schedule: clock.schedule,
    cancelSchedule: clock.cancel,
    fetchStatus: () => new Promise((resolve) => { release = () => resolve({ job: READY_JOB, document: DOCUMENT }); }),
    onProgress: () => events.push('progress'),
    onReady: () => events.push('ready'),
    onFailed: () => events.push('failed'),
    onError: () => events.push('error'),
  });

  const pending = clock.runNext();
  stop();
  release();
  await pending;

  assert.deepEqual(events, []);
  assert.equal(clock.jobs.size, 0);
});

test('опрос без идентификатора задачи не запускается', () => {
  assert.throws(() => startGenerationPolling({
    jobId: '',
    fetchStatus: async () => ({}),
    onProgress: () => {},
    onReady: () => {},
    onFailed: () => {},
    onError: () => {},
  }), /задач/i);
});

test('клиент умеет опросить задачу, повторить её и найти работу по делу', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');

  assert.match(api, /\/miniapp\/documents\/generation\//);
  assert.match(api, /generationStatus/);
  assert.match(api, /retryGeneration/);
  assert.match(api, /caseGeneration/);
});

test('экран следует за состоянием задачи, а не выдаёт её описание за документ', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.match(app, /import \{ interpretGeneration, startGenerationPolling \} from '\.\/generationJob'/);
  assert.match(app, /startGenerationPolling\(\{/, 'прогресс подготовки не опрашивается');
  assert.match(app, /korganApi\.caseGeneration\(/, 'начатая подготовка не восстанавливается при открытии дела');
  assert.match(app, /korganApi\.retryGeneration\(/, 'прерванную подготовку нельзя повторить без новой оплаты');

  const generate = app.slice(app.indexOf('const generateDocument'), app.indexOf('const retryGeneration'));
  assert.ok(
    !/setDocumentResult|setScreen\('ready'\)/.test(generate),
    'ответ на запуск подготовки всё ещё показывается как готовый документ',
  );
});

test('технические имена стадий не доходят до экрана', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  const screen = app.slice(app.indexOf("if (screen === 'generating'"), app.indexOf("if (screen === 'ready')"));

  assert.match(screen, /stageText\(generation\.stage, language\)/);
  assert.ok(
    !/\{generation\.stage\}/.test(screen),
    'на экране показывается служебное имя стадии конвейера',
  );
  assert.match(screen, /aria-valuenow=\{generation\.progress\}/, 'проценты не приходят с сервера');
});

test('запуск подготовки больше не ждёт готовый документ в ответе', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');
  const start = api.slice(api.indexOf('generateDocument:'), api.indexOf('uploadDocumentReceipt,'));

  assert.ok(
    !/requireProfessionalDocument/.test(start),
    'запуск задачи всё ещё требует готовый документ прямо в ответе',
  );
  assert.ok(
    !/timeoutMs: 180000/.test(start),
    'ожидание документа внутри запроса больше не нужно',
  );
});
