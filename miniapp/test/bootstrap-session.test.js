/**
 * Startup Mini App должен иметь одного сетевого владельца. Повторный вход,
 * remount или retry во время медленного consent не должны порождать вторую
 * волну /health + /parity + /consent и не должны обрывать первый запрос.
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
  for (const name of Object.keys(api)) api[name] = async () => { calls += 1; };

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

test('cleanup делает ответ устаревшим, но не обрывает сетевой startup', async () => {
  let resolveHealth;
  let startupSignal;
  const api = acceptedApi();
  api.health = options => {
    startupSignal = options.signal;
    return new Promise(resolve => { resolveHealth = resolve; });
  };
  const session = createBootstrapSession({ api, isBackendConnected: () => true, termsVersion: TERMS_VERSION });

  const pending = session.run();
  assert.equal(typeof resolveHealth, 'function');
  session.cancel();
  assert.equal(startupSignal.aborted, false);
  resolveHealth({ status: 'ok' });

  assert.deepEqual(await pending, { kind: 'stale' });
  assert.equal(startupSignal.aborted, false);
});

test('повторный startup ждёт тот же запрос вместо второй сетевой волны', async () => {
  let resolveHealth;
  const calls = [];
  const api = acceptedApi(calls);
  api.health = options => {
    calls.push(['health', options]);
    return new Promise(resolve => { resolveHealth = resolve; });
  };
  const session = createBootstrapSession({ api, isBackendConnected: () => true, termsVersion: TERMS_VERSION });

  const first = session.run();
  const second = session.run();
  assert.equal(typeof resolveHealth, 'function');
  assert.deepEqual(calls.map(([name]) => name).sort(), ['consent', 'health']);
  resolveHealth({ status: 'ok' });

  assert.deepEqual(await first, { kind: 'stale' });
  const latest = await second;
  assert.equal(latest.kind, 'ready');
  assert.equal(latest.consent, true);
  assert.deepEqual(calls.map(([name]) => name).sort(), ['cases', 'consent', 'health', 'pricing']);
});

test('два React экземпляра делят один bootstrap flight', async () => {
  let releaseConsent;
  const calls = [];
  const api = acceptedApi(calls);
  api.consentStatus = options => {
    calls.push(['consent', options]);
    return new Promise(resolve => { releaseConsent = resolve; });
  };
  const one = createBootstrapSession({ api, isBackendConnected: () => true, termsVersion: TERMS_VERSION });
  const two = createBootstrapSession({ api, isBackendConnected: () => true, termsVersion: TERMS_VERSION });

  const first = one.run();
  const second = two.run();
  assert.deepEqual(calls.map(([name]) => name).sort(), ['consent', 'health']);
  releaseConsent({ accepted: true, terms_version: TERMS_VERSION });

  assert.equal((await first).kind, 'ready');
  assert.equal((await second).kind, 'ready');
  assert.deepEqual(calls.map(([name]) => name).sort(), ['cases', 'consent', 'health', 'pricing']);
});

test('ошибка startup возвращается отдельно и не становится отказом от условий', async () => {
  const failure = new Error('Failed to fetch');
  const api = acceptedApi();
  api.health = async () => { throw failure; };
  const session = createBootstrapSession({ api, isBackendConnected: () => true, termsVersion: TERMS_VERSION });

  const result = await session.run();
  assert.equal(result.kind, 'error');
  assert.equal(result.error, failure);
  assert.equal('consent' in result, false);
});
