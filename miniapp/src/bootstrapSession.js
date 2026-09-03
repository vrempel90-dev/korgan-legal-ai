import { resolveConsent } from './consentAuthority.js';

const sharedFlights = new WeakMap();

function unavailableError() {
  const error = new Error('KORGAN API не подключён');
  error.code = 'KORGAN_API_NOT_CONNECTED';
  return error;
}

function sharedBootstrap(api, termsVersion) {
  const current = sharedFlights.get(api);
  if (current?.termsVersion === termsVersion) return current.promise;

  // Startup не обрывается при повторном рендере/нажатии retry. Раньше отмена
  // медленного /miniapp/consent давала Railway 499 и запускала вторую волну
  // /health + /parity + /consent. Все экземпляры Mini App делят один запрос,
  // а generation-token решает, какой экран имеет право применить результат.
  const controller = new AbortController();
  const options = { signal: controller.signal };

  let promise;
  promise = (async () => {
    const [health, serverConsent] = await Promise.all([
      api.health(options),
      api.consentStatus(options),
    ]);

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

    return {
      kind: 'ready',
      consent: true,
      health,
      cases: caseResult?.cases || [],
      pricing,
    };
  })().catch(error => ({ kind: 'error', error })).finally(() => {
    if (sharedFlights.get(api)?.promise === promise) sharedFlights.delete(api);
  });

  sharedFlights.set(api, { termsVersion, promise });
  return promise;
}

/**
 * Владеет startup-состоянием Mini App. Повторные или параллельные запуски не
 * создают новые сетевые волны: они ждут один общий запрос, а устаревший экран
 * не имеет права применить его результат.
 */
export function createBootstrapSession({ api, isBackendConnected, termsVersion }) {
  let generation = 0;

  function cancel() {
    generation += 1;
  }

  async function run() {
    generation += 1;
    const runGeneration = generation;
    if (!isBackendConnected()) {
      return { kind: 'unavailable', error: unavailableError() };
    }

    const result = await sharedBootstrap(api, termsVersion);
    if (generation !== runGeneration) return { kind: 'stale' };
    return result;
  }

  return { run, cancel };
}
