import test from 'node:test';
import assert from 'node:assert/strict';

import { lifecycleLabel, projectCaseLifecycle } from '../src/caseLifecycle.js';

test('готовый сохранённый документ сильнее старого payment state', () => {
  assert.equal(projectCaseLifecycle({
    caseData: { status: 'document_ready', has_document: true, filename: 'claim.docx' },
    payment: { status: 'awaiting_admin' },
  }), 'ready');
});

test('generation state берётся с backend и не выводится из процентов', () => {
  assert.equal(projectCaseLifecycle({
    caseData: { status: 'materials_ready' },
    generation: { status: 'queued', progress: 0 },
  }), 'queued');
  assert.equal(projectCaseLifecycle({
    caseData: { status: 'materials_ready' },
    generation: { status: 'running', progress: 80 },
  }), 'running');
  assert.equal(projectCaseLifecycle({
    caseData: { status: 'materials_ready' },
    generation: { status: 'failed', progress: 80 },
  }), 'failed');
});

test('ручная оплата сохраняет существующие серверные статусы', () => {
  assert.equal(projectCaseLifecycle({ caseData: {}, payment: { status: 'pending_receipt' } }), 'payment_pending');
  assert.equal(projectCaseLifecycle({ caseData: {}, payment: { status: 'awaiting_admin' } }), 'payment_pending');
  assert.equal(projectCaseLifecycle({ caseData: {}, payment: { status: 'approved' } }), 'paid');
  assert.equal(projectCaseLifecycle({ caseData: {}, payment: { status: 'rejected' } }), 'payment_failed');
});

test('материалы и новое дело имеют отдельные состояния', () => {
  assert.equal(projectCaseLifecycle({ caseData: { status: 'materials_ready', materials_count: 2 } }), 'materials_ready');
  assert.equal(projectCaseLifecycle({ caseData: { status: 'case_created', materials_count: 0 } }), 'case_created');
});

test('подписи lifecycle доступны на русском и казахском', () => {
  assert.equal(lifecycleLabel('running', 'ru'), 'Документ готовится');
  assert.equal(lifecycleLabel('running', 'kk'), 'Құжат дайындалып жатыр');
});
