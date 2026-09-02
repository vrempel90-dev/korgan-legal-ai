import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isAmbiguousGenerationStartError,
  recoverGenerationStart,
} from '../src/generationStartRecovery.js';

const timeout = Object.assign(new Error('timeout'), { code: 'KORGAN_API_TIMEOUT' });

test('таймаут запуска восстанавливает уже созданную задачу без второго POST', async () => {
  let reads = 0;
  let sleeps = 0;
  const recovered = await recoverGenerationStart({
    caseId: 'case-1',
    error: timeout,
    attempts: 3,
    sleep: async () => { sleeps += 1; },
    fetchCaseGeneration: async () => {
      reads += 1;
      if (reads === 1) return { job: null };
      return {
        job: {
          job_id: 'job-1',
          case_id: 'case-1',
          status: 'running',
          stage: 'legal_research',
          progress: 20,
          document_ready: false,
        },
      };
    },
  });

  assert.equal(reads, 2);
  assert.equal(sleeps, 1);
  assert.equal(recovered.generation_started, true);
  assert.equal(recovered.recovered_after_ambiguous_start, true);
  assert.equal(recovered.job.job_id, 'job-1');
});

test('успешно завершившаяся задача тоже восстанавливается после таймаута', async () => {
  const recovered = await recoverGenerationStart({
    caseId: 'case-1',
    error: timeout,
    attempts: 1,
    fetchCaseGeneration: async () => ({
      job: {
        job_id: 'job-1',
        case_id: 'case-1',
        status: 'succeeded',
        stage: 'completed',
        progress: 100,
        document_ready: true,
      },
      document: { filename: 'claim.docx' },
    }),
  });

  assert.equal(recovered.generation_started, false);
  assert.equal(recovered.document.filename, 'claim.docx');
});

test('обычная HTTP-ошибка не маскируется восстановлением', async () => {
  const httpError = Object.assign(new Error('bad request'), {
    code: 'KORGAN_API_HTTP_ERROR',
    status: 422,
  });
  let reads = 0;

  await assert.rejects(() => recoverGenerationStart({
    caseId: 'case-1',
    error: httpError,
    fetchCaseGeneration: async () => { reads += 1; return { job: null }; },
  }), (error) => error === httpError);

  assert.equal(reads, 0);
  assert.equal(isAmbiguousGenerationStartError(httpError), false);
});

test('если сервер не сохранил задачу, исходный таймаут остаётся ошибкой', async () => {
  let reads = 0;
  await assert.rejects(() => recoverGenerationStart({
    caseId: 'case-1',
    error: timeout,
    attempts: 3,
    sleep: async () => {},
    fetchCaseGeneration: async () => { reads += 1; return { job: null }; },
  }), (error) => error === timeout);

  assert.equal(reads, 3);
});
