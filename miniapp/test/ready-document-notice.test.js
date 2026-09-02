import test from 'node:test';
import assert from 'node:assert/strict';

import {
  acknowledgeReadyDocument,
  isReadyDocumentAcknowledged,
  openReadyDocument,
} from '../src/readyDocumentNotice.js';

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
  };
}

test('acknowledgement is scoped to exact case and generation job', () => {
  const storage = memoryStorage();
  assert.equal(isReadyDocumentAcknowledged('KOR-1', 'job-1', storage), false);
  acknowledgeReadyDocument('KOR-1', 'job-1', storage);
  assert.equal(isReadyDocumentAcknowledged('KOR-1', 'job-1', storage), true);
  assert.equal(isReadyDocumentAcknowledged('KOR-1', 'job-2', storage), false);
  assert.equal(isReadyDocumentAcknowledged('KOR-2', 'job-1', storage), false);
});

test('successful server-backed opening hides only that ready notification', async () => {
  const storage = memoryStorage();
  const api = {
    documentAccess: async caseId => ({
      ok: true,
      case_id: caseId,
      filename: 'claim.docx',
      download_url: 'https://example.test/signed.docx',
    }),
  };
  const opened = [];
  const result = await openReadyDocument({
    caseId: 'KOR-1',
    jobId: 'job-1',
    api,
    storage,
    openDocument: async (url, filename) => {
      opened.push([url, filename]);
      return true;
    },
  });

  assert.equal(result.ok, true);
  assert.deepEqual(opened, [['https://example.test/signed.docx', 'claim.docx']]);
  assert.equal(isReadyDocumentAcknowledged('KOR-1', 'job-1', storage), true);
});

test('failed opening never acknowledges or removes a future ready action', async () => {
  const storage = memoryStorage();
  const api = {
    documentAccess: async () => ({
      ok: true,
      filename: 'claim.docx',
      download_url: 'https://example.test/signed.docx',
    }),
  };

  await assert.rejects(
    openReadyDocument({
      caseId: 'KOR-1',
      jobId: 'job-1',
      api,
      storage,
      openDocument: async () => false,
    }),
    /Документ не был открыт/,
  );
  assert.equal(isReadyDocumentAcknowledged('KOR-1', 'job-1', storage), false);
});
