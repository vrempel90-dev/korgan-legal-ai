import { resolveConsent } from './consentAuthority.js';

function unavailableError() {
  const error = new Error('KORGAN API не подключён');
  error.code = 'KORGAN_API_NOT_CONNECTED';
  return error;
}

/**
 * Владеет startup-запросами Mini App. Каждый новый запуск отменяет предыдущий,
 * поэтому завершившаяся старая сессия не может перезаписать актуальное состояние.
 */
export function createBootstrapSession({ api, isBackendConnected, termsVersion }) {
  let active = null;
  let generation = 0;

  function cancel() {
    generation += 1;
    active?.abort();
    active = null;
  }

  async function run() {
    cancel();
    const runGeneration = generation;
    if (!isBackendConnected()) {
      return { kind: 'unavailable', error: unavailableError() };
    }

    const controller = new AbortController();
    active = controller;
    const options = { signal: controller.signal };
    const stale = () => controller.signal.aborted || generation !== runGeneration;

    try {
      const [health, serverConsent] = await Promise.all([
        api.health(options),
        api.consentStatus(options),
      ]);
      if (stale()) return { kind: 'stale' };

      const decision = resolveConsent(serverConsent, termsVersion);
      if (!decision.accepted) {
        return {
          kind: 'ready',
          consent: false,
          health,
          cases: [],
          pricing: null,
        };
      }

      const [caseResult, pricing] = await Promise.all([
        api.listCases(options),
        api.pricing(options),
      ]);
      if (stale()) return { kind: 'stale' };

      return {
        kind: 'ready',
        consent: true,
        health,
        cases: caseResult?.cases || [],
        pricing,
      };
    } catch (error) {
      if (stale()) return { kind: 'stale' };
      return { kind: 'error', error };
    } finally {
      if (generation === runGeneration) active = null;
    }
  }

  return { run, cancel };
}
