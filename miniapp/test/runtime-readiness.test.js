/**
 * Проверка готовности бэкенда не должна отказывать из-за номера версии.
 *
 * Клиент требовал parity.api_version === '0.9.0'. Развёрнутое приложение
 * (korgan.miniapp_api_recovery_cors) отдаёт '1.0.0': слой v5 поднял версию, а
 * строка в клиенте осталась прежней. Совпадали все содержательные поля —
 * legal_runtime, вся цепочка сервисов, целевое качество, предварительный
 * фолбэк, ручная сверка платежа, — и не совпадало только число.
 *
 * Последствие не косметическое: boot() ловил исключение, ставил connection
 * 'down', и мини-апп целиком показывал «нет связи» с заблокированными
 * кнопками. Равенство версий ничего не защищало и гарантировало отказ при
 * каждом повышении версии бэкенда.
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

test('развёрнутый бэкенд признаётся готовым', () => {
  const result = requireProfessionalRuntime(HEALTH, PARITY);

  assert.equal(result.status, 'ok');
  assert.equal(result.parity.api_version, '1.0.0');
});

test('повышение версии бэкенда не выводит приложение из строя', () => {
  // Клиент не обязан обновляться из-за номера версии, если содержательные
  // поля контракта на месте.
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

test('при платных документах ручная сверка обязана быть включена', () => {
  // Автоматическая выдача документа за деньги без сверки платежа человеком —
  // не то, что делает развёрнутый бэкенд.
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
