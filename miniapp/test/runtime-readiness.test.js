/**
 * Проверка готовности бэкенда не должна отказывать из-за номера версии и
 * должна различать два безопасных пути подтверждения оплаты: legacy manual и
 * production Tole automatic confirmation.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { requireProfessionalDocument, requireProfessionalRuntime } from '../src/runtimeReadiness.js';

/** Ответы, снятые с собранного korgan.miniapp_api_recovery_cors. */
const HEALTH = {
  status: 'ok',
  legal_runtime: 'strict_bot',
  word_quality_target: '10/10',
  preliminary_fallback: true,
};

const PARITY = {
  status: 'ok',
  api_version: '1.0.0',
  service_outer: 'ClaimPipelineV2Adapter',
  service_claim_mux: 'ClaimServiceMux',
  service_stable: 'PretrialResponseProductionService',
  word_quality_target: '10/10',
  preliminary_fallback: true,
  consultation_limit_enabled: false,
  document_payments_enabled: false,
  document_manual_confirmation: true,
};

const TOLE_PARITY = {
  ...PARITY,
  document_payments_enabled: true,
  document_payment_provider: 'tole',
  document_manual_confirmation: false,
  automatic_payment_confirmation: true,
  tole_configured: true,
};

test('развёрнутый бэкенд признаётся готовым', () => {
  const result = requireProfessionalRuntime(HEALTH, PARITY);

  assert.equal(result.status, 'ok');
  assert.equal(result.parity.api_version, '1.0.0');
});

test('повышение версии бэкенда не выводит приложение из строя', () => {
  assert.doesNotThrow(() => requireProfessionalRuntime(HEALTH, { ...PARITY, api_version: '1.4.2' }));
});

test('ответ без версии не признаётся ответом KORGAN', () => {
  assert.throws(() => requireProfessionalRuntime(HEALTH, { ...PARITY, api_version: '' }));
  assert.throws(() => requireProfessionalRuntime(HEALTH, { ...PARITY, api_version: undefined }));
});

test('подмена юридического движка по-прежнему останавливает приложение', () => {
  assert.throws(() => requireProfessionalRuntime({ ...HEALTH, legal_runtime: 'demo' }, PARITY));
  assert.throws(() => requireProfessionalRuntime(HEALTH, { ...PARITY, service_stable: 'StubService' }));
  assert.throws(() => requireProfessionalRuntime({ ...HEALTH, word_quality_target: '7/10' }, PARITY));
});

test('production Tole automatic confirmation признаётся безопасным платёжным путём', () => {
  const result = requireProfessionalRuntime(HEALTH, TOLE_PARITY);

  assert.equal(result.parity.document_payment_provider, 'tole');
  assert.equal(result.parity.automatic_payment_confirmation, true);
  assert.equal(result.parity.document_manual_confirmation, false);
});

test('автоматическая оплата fail-closed для неизвестного или недонастроенного провайдера', () => {
  assert.throws(() => requireProfessionalRuntime(HEALTH, {
    ...TOLE_PARITY,
    document_payment_provider: 'unknown',
  }));
  assert.throws(() => requireProfessionalRuntime(HEALTH, {
    ...TOLE_PARITY,
    automatic_payment_confirmation: false,
  }));
  assert.throws(() => requireProfessionalRuntime(HEALTH, {
    ...TOLE_PARITY,
    tole_configured: false,
  }));
});

test('платные документы без manual или verified Tole confirmation блокируют приложение', () => {
  assert.throws(() => requireProfessionalRuntime(HEALTH, {
    ...PARITY,
    document_payments_enabled: true,
    document_manual_confirmation: false,
  }));
});

test('документ без метаданных выпуска не принимается', () => {
  assert.throws(() => requireProfessionalDocument({ filing_ready: true }));
  assert.throws(() => requireProfessionalDocument({
    filing_ready: true,
    release_status: 'unknown',
    document_base64: 'AAA',
  }));
});

test('документ с полными метаданными выпуска принимается', () => {
  const payload = { filing_ready: false, release_status: 'preliminary', document_base64: 'AAA' };

  assert.equal(requireProfessionalDocument(payload), payload);
});