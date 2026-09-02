import test from 'node:test';
import assert from 'node:assert/strict';

import { caseProgressSnapshot } from '../src/caseProgressState.js';

test('running progress uses backend percentage and stage without inventing values', () => {
  const snapshot = caseProgressSnapshot({
    job: {
      job_id: 'job-1',
      case_id: 'case-1',
      status: 'running',
      stage: 'legal_research',
      progress: 42,
      document_ready: false,
      retryable: false,
    },
  }, 'ru');

  assert.equal(snapshot.kind, 'running');
  assert.equal(snapshot.progress, 42);
  assert.equal(snapshot.label, 'Проверяю право и источники');
  assert.equal(snapshot.poll, true);
});

test('ready is shown only when backend returned a saved document', () => {
  const snapshot = caseProgressSnapshot({
    job: {
      job_id: 'job-2',
      case_id: 'case-2',
      status: 'succeeded',
      stage: 'completed',
      progress: 100,
      document_ready: true,
      retryable: false,
    },
    document: { filename: 'claim.docx' },
  });

  assert.deepEqual(snapshot, {
    kind: 'ready',
    progress: 100,
    label: 'Документ готов',
    poll: false,
  });
});

test('idle cases display zero instead of fake progress', () => {
  const snapshot = caseProgressSnapshot({ job: null });
  assert.equal(snapshot.kind, 'idle');
  assert.equal(snapshot.progress, 0);
  assert.equal(snapshot.poll, false);
});

test('malformed or unavailable backend status never becomes fake READY', () => {
  const snapshot = caseProgressSnapshot({});
  assert.equal(snapshot.kind, 'unavailable');
  assert.equal(snapshot.progress, null);
  assert.equal(snapshot.poll, true);
});
