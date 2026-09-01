/**
 * Startup Mini App должен иметь одного владельца: один запуск проверяет серверное
 * согласие и ровно один раз загружает workspace. Ответ завершившегося старого
 * запуска не должен возвращать интерфейс к устаревшей сессии.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createBootstrapSession } from '../src/bootstrapSession.js';

const TERMS_VERSION = '2026-08-16-v1';

function acceptedApi(calls = []) {
  return {
    health: async options => { calls.push(['health', options]); return { status: 'ok' }; },
    consentStatus: async options => {
      calls.push(['consent', options]);
      return { accepted: true, terms_version: TERMS_VERSION };
    },
    listCases: async options => { calls.push(['cases', options]); return { cases: [{ id: 'K-1' }] }; },
    pricing: async options => { calls.push(['pricing', options]); return { document_price_kzt: 5000 }; },
  };
}

test('принятое серверное согласие загружает workspace ровно один раз', async () => {
  const calls = [];
  const session = createBootstrapSession({
    api: acceptedApi(calls),
    isBackendConnected: () => true,
    termsVersion: TERMS_VERSION,
  });

  const result = await session.run();

  assert.equal(result.kind, 'ready');
  assert.equal(result.consent, true);
  assert.deepEqual(result.cases, [{ id: 'K-1' }]);
  assert.deepEqual(result.pricing, { document_price_kzt: 5000 });
  assert.deepEqual(calls.map(([name]) => name).sort(), ['cases', 'consent', 'health', 'pricing']);
  assert.equal(calls.every(([, options]) => options.signal instanceof AbortSignal), true);
});

test('непринятые условия не открывают и не запрашивают workspace', async () => {
  const workspaceCalls = [];
  const session = createBootstrapSession({
    api: {
      health: async () => ({ status: 'ok' }),
      consentStatus: async () => ({ accepted: false, terms_version: TERMS_VERSION }),
      listCases: async () => { workspaceCalls.push('cases'); },
      pricing: async () => { workspaceCalls.push('pricing'); },
    },
    isBackendConnected: () => true,
    termsVersion: TERMS_VERSION,
  });

  const result = await session.run();

  assert.equal(result.kind, 'ready');
  assert.equal(result.consent, false);
  assert.deepEqual(result.cases, []);
  assert.equal(result.pricing, null);
  assert.deepEqual(workspaceCalls, []);
});

test('отсутствующий API возвращает явное unavailable-состояние без запросов', async () => {
  let calls = 0;
  const api = acceptedApi();
  for (const name of Object.keys(api)) {
    api[name] = async () => { calls += 1; };
  }
  const session = createBootstrapSession({
    api,
    isBackendConnected: () => false,
    termsVersion: TERMS_VERSION,
  });

  const result = await session.run();

  assert.equal(result.kind, 'unavailable');
  assert.equal(result.error.code, 'KORGAN_API_NOT_CONNECTED');
  assert.equal(calls, 0);
});

test('cleanup отменяет startup и помечает поздний ответ устаревшим', async () => {
  let resolveHealth;
  let startupSignal;
  const api = acceptedApi();
  api.health = options => {
    startupSignal = options.signal;
    return new Promise(resolve => { resolveHealth = resolve; });
  };
  const session = createBootstrapSession({
    api,
    isBackendConnected: () => true,
    termsVersion: TERMS_VERSION,
  });

  const pending = session.run();
  assert.equal(typeof resolveHealth, 'function');
  session.cancel();
  resolveHealth({ status: 'ok' });
  const result = await pending;

  assert.equal(startupSignal.aborted, true);
  assert.deepEqual(result, { kind: 'stale' });
});

test('новый startup выигрывает у позднего ответа предыдущего', async () => {
  let resolveFirstHealth;
  let healthCall = 0;
  let consentCall = 0;
  const api = {
    health: async () => {
      healthCall += 1;
      if (healthCall === 1) return new Promise(resolve => { resolveFirstHealth = resolve; });
      return { status: 'new' };
    },
    consentStatus: async () => {
      consentCall += 1;
      return consentCall === 1
        ? { accepted: true, terms_version: TERMS_VERSION }
        : { accepted: false, terms_version: TERMS_VERSION };
    },
    listCases: async () => ({ cases: [{ id: 'STALE' }] }),
    pricing: async () => ({ document_price_kzt: 1 }),
  };
  const session = createBootstrapSession({
    api,
    isBackendConnected: () => true,
    termsVersion: TERMS_VERSION,
  });

  const first = session.run();
  assert.equal(typeof resolveFirstHealth, 'function');
  const second = await session.run();
  resolveFirstHealth({ status: 'old' });

  assert.equal(second.kind, 'ready');
  assert.equal(second.consent, false);
  assert.deepEqual(await first, { kind: 'stale' });
});

test('ошибка startup возвращается отдельно и не становится отказом от условий', async () => {
  const failure = new Error('Failed to fetch');
  const api = acceptedApi();
  api.health = async () => { throw failure; };
  const session = createBootstrapSession({
    api,
    isBackendConnected: () => true,
    termsVersion: TERMS_VERSION,
  });

  const result = await session.run();

  assert.equal(result.kind, 'error');
  assert.equal(result.error, failure);
  assert.equal('consent' in result, false);
});
