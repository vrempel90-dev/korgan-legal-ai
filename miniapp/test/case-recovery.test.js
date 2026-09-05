import test from 'node:test';
import assert from 'node:assert/strict';

import { recoverCaseWorkspace } from '../src/caseRecovery.js';

const CASE = { id: 'case-1', status: 'materials_ready', has_document: false };
const JOB = {
  job_id: 'job-1', case_id: 'case-1', status: 'running', stage: 'legal_research',
  progress: 20, document_ready: false, retryable: false, error: '',
};

test('reopen возвращает пользователя к реальной идущей задаче', async () => {
  const result = await recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: CASE }),
    caseGeneration: async () => ({ job: JOB }),
  });

  assert.equal(result.view, 'generating');
  assert.equal(result.generation.jobId, 'job-1');
  assert.equal(result.generation.progress, 20);
});

test('succeeded после reopen открывает READY только с реальным документом', async () => {
  const document = { case_id: 'case-1', status: 'document_ready', filename: 'claim.docx' };
  const result = await recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: { ...CASE, status: 'document_ready', has_document: true } }),
    caseGeneration: async () => ({
      job: { ...JOB, status: 'succeeded', stage: 'completed', progress: 100, document_ready: true },
      document,
    }),
  });

  assert.equal(result.view, 'ready');
  assert.equal(result.document.filename, 'claim.docx');
});

test('сохранённый документ восстанавливается даже без generation job', async () => {
  let reads = 0;
  const result = await recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: { ...CASE, status: 'document_ready', has_document: true } }),
    caseGeneration: async () => ({ job: null }),
    getDocument: async () => { reads += 1; return { filename: 'claim.docx', status: 'document_ready' }; },
  });

  assert.equal(reads, 1);
  assert.equal(result.view, 'ready');
  assert.equal(result.document.filename, 'claim.docx');
});

test('сбой чтения generation не превращает обычное дело в ложный failure', async () => {
  const result = await recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: CASE }),
    caseGeneration: async () => { throw new Error('temporary network error'); },
  });

  assert.equal(result.view, 'case');
  assert.equal(result.document, null);
  assert.match(result.generationError.message, /network/);
});

test('чужое или неполное дело отвергается', async () => {
  await assert.rejects(() => recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: { id: 'case-2' } }),
    caseGeneration: async () => ({ job: null }),
  }), /выбранное дело/i);
});

test('после перезагрузки идущая задача показывает реальные шаги, а не пустой список', async () => {
  const { generationSteps } = await import('../src/generationStages.js');
  const running = { ...JOB, stage: 'legal_qa', progress: 70 };
  const result = await recoverCaseWorkspace('case-1', {
    getCase: async () => ({ case: CASE }),
    caseGeneration: async () => ({ job: running }),
  });

  assert.equal(result.view, 'generating');
  assert.equal(result.generation.stage, 'legal_qa');

  // Список шагов восстанавливается из стадии сервера: закрытие Mini App не
  // отбрасывает подготовку в начало и не выдаёт пустой экран за живую работу.
  const steps = generationSteps(result.generation);
  assert.deepEqual(steps.map((item) => item.state), [
    'done', 'done', 'done', 'active', 'pending', 'pending',
  ]);
});
