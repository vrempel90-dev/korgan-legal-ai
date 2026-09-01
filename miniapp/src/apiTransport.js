const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_GET_RETRIES = 1;
const TRANSIENT_STATUSES = new Set([429, 502, 503, 504]);

function apiError(message, properties = {}) {
  const error = new Error(message);
  Object.assign(error, properties);
  return error;
}

function delay(milliseconds) {
  return new Promise(resolve => globalThis.setTimeout(resolve, milliseconds));
}

async function parsePayload(response) {
  const contentType = response.headers.get('content-type') || '';
  const raw = await response.text();
  if (!contentType.toLowerCase().includes('application/json')) return raw;

  if (!raw.trim()) {
    if (!response.ok) return {};
    throw apiError('KORGAN API вернул некорректный ответ', {
      code: 'KORGAN_API_INVALID_RESPONSE',
    });
  }
  try {
    return JSON.parse(raw);
  } catch {
    if (!response.ok) return raw;
    throw apiError('KORGAN API вернул некорректный ответ', {
      code: 'KORGAN_API_INVALID_RESPONSE',
    });
  }
}

function responseError(response, payload) {
  const detail = typeof payload === 'object' && payload !== null
    ? (payload.detail || payload.message)
    : payload;
  // Отказ в подписи Telegram — не обычная ошибка запроса: её текст служебный и
  // англоязычный, а повтор бесполезен, пока Mini App не открыт заново. Экран
  // объясняет это сам, поэтому сюда серверная формулировка не попадает.
  if (response.status === 401 || response.status === 403) {
    return apiError('Подпись Telegram недействительна', {
      code: 'KORGAN_API_UNAUTHORIZED',
      status: response.status,
      payload,
    });
  }
  return apiError(detail || `KORGAN_API_${response.status}`, {
    code: 'KORGAN_API_HTTP_ERROR',
    status: response.status,
    payload,
  });
}

function networkError(error) {
  return apiError('Не удалось подключиться к KORGAN API', {
    code: 'KORGAN_API_NETWORK_ERROR',
    cause: error,
  });
}

function canRetry(error, method, attempt, maxGetRetries) {
  if (method !== 'GET' || attempt >= maxGetRetries) return false;
  return error?.code === 'KORGAN_API_NETWORK_ERROR' || TRANSIENT_STATUSES.has(error?.status);
}

function requestSignal(externalSignal, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) abortFromCaller();
  else externalSignal?.addEventListener?.('abort', abortFromCaller, { once: true });

  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      globalThis.clearTimeout(timer);
      externalSignal?.removeEventListener?.('abort', abortFromCaller);
    },
  };
}

/** Создаёт единый HTTP-транспорт для всех запросов Mini App. */
export function createApiTransport({
  baseUrl,
  getTelegramInitData = () => '',
  fetchImpl = globalThis.fetch?.bind(globalThis),
  timeoutMs: defaultTimeoutMs = DEFAULT_TIMEOUT_MS,
  maxGetRetries = DEFAULT_GET_RETRIES,
  retryDelay = attempt => delay(250 * attempt),
}) {
  const base = String(baseUrl || '').replace(/\/+$/, '');

  return async function request(path, options = {}) {
    if (!base) {
      throw apiError('KORGAN_API_NOT_CONNECTED', { code: 'KORGAN_API_NOT_CONNECTED' });
    }
    if (typeof fetchImpl !== 'function') {
      throw apiError('KORGAN API transport is unavailable', { code: 'KORGAN_API_NOT_CONNECTED' });
    }

    const method = String(options.method || 'GET').toUpperCase();
    const perRequestTimeout = Number(options.timeoutMs ?? defaultTimeoutMs);
    const timeout = Number.isFinite(perRequestTimeout) && perRequestTimeout > 0
      ? perRequestTimeout
      : defaultTimeoutMs;
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const headers = {
      ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    };
    const initData = String(getTelegramInitData() || '');
    if (initData) headers['X-Telegram-Init-Data'] = initData;

    const { timeoutMs: _timeoutMs, signal: externalSignal, ...fetchOptions } = options;
    let attempt = 0;
    while (true) {
      const scoped = requestSignal(externalSignal, timeout);
      try {
        const response = await fetchImpl(`${base}${path}`, {
          ...fetchOptions,
          method,
          headers,
          signal: scoped.signal,
        });
        const payload = await parsePayload(response);
        if (!response.ok) throw responseError(response, payload);
        return payload;
      } catch (caught) {
        let error = caught;
        if (scoped.timedOut()) {
          error = apiError('Превышено время ожидания ответа KORGAN API', {
            code: 'KORGAN_API_TIMEOUT',
            cause: caught,
          });
        } else if (externalSignal?.aborted) {
          error = apiError('Запрос KORGAN API отменён', {
            code: 'KORGAN_API_ABORTED',
            cause: caught,
          });
        } else if (
          caught?.name === 'TypeError'
          || caught?.name === 'NetworkError'
          || (caught?.name === 'AbortError' && !scoped.timedOut())
        ) {
          error = networkError(caught);
        }

        if (!canRetry(error, method, attempt, maxGetRetries)) throw error;
        attempt += 1;
        await retryDelay(attempt);
      } finally {
        scoped.cleanup();
      }
    }
  };
}
