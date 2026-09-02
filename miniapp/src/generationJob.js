/**
 * Состояние подготовки документа читается с сервера и нигде не досочиняется.
 *
 * Подготовка документа не помещается в один HTTP-запрос, поэтому сервер отвечает
 * описанием задачи, а не готовым файлом. Клиенту остаётся ровно две обязанности:
 * честно прочитать это описание и не объявить готовность раньше, чем документ
 * действительно сохранён.
 */

const MISSING_JOB = 'Сервис не сообщил состояние подготовки документа';
const MISSING_DOCUMENT = 'Подготовка завершена, но документ не получен';
const MISSING_PAYMENT = 'Сервис не сообщил условия оплаты документа';
const JOB_STATUSES = new Set(['queued', 'running', 'succeeded', 'failed']);
const LIFECYCLE_EVENT = 'korgan:generation-lifecycle';

function normalizeJob(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const jobId = String(raw.job_id || '').trim();
  const status = String(raw.status || '').trim();
  const stage = String(raw.stage || '').trim();
  if (!jobId || !stage || !JOB_STATUSES.has(status)) return null;
  if (typeof raw.progress !== 'number' || !Number.isFinite(raw.progress)) return null;
  return {
    jobId,
    caseId: String(raw.case_id || ''),
    status,
    stage,
    progress: Math.max(0, Math.min(Math.round(raw.progress), 100)),
    documentReady: raw.document_ready === true,
    retryable: raw.retryable === true,
    error: String(raw.error || ''),
  };
}

function normalizeDocument(raw) {
  if (!raw || typeof raw !== 'object') return null;
  return String(raw.filename || '').trim() ? raw : null;
}

function publishLifecycle(job, document = null) {
  if (!job || !job.jobId || !job.caseId) return;
  const target = globalThis.window;
  const EventClass = globalThis.CustomEvent;
  if (!target || typeof target.dispatchEvent !== 'function' || typeof EventClass !== 'function') return;
  target.dispatchEvent(new EventClass(LIFECYCLE_EVENT, {
    detail: { job, document },
  }));
}

/**
 * Приводит любой ответ о подготовке документа к одному из состояний экрана.
 *
 * Состояния: `payment_required`, `running`, `ready`, `failed`, `idle`.
 * Всё, что не разбирается однозначно, становится ошибкой — показать «идёт
 * подготовка» на непонятном ответе значит соврать о работе, которой нет.
 */
export function interpretGeneration(result) {
  const payload = result && typeof result === 'object' ? result : {};

  if (payload.payment_required === true) {
    const payment = payload.payment;
    if (!payment || typeof payment !== 'object' || !String(payment.order_id || '').trim()) {
      throw new Error(MISSING_PAYMENT);
    }
    return { status: 'payment_required', job: null, document: null, payment };
  }

  // Явный `null` — это ответ «по этому делу подготовку не начинали».
  // Отсутствие поля — это ответ, который клиент не понял.
  if ('job' in payload && payload.job === null) {
    return { status: 'idle', job: null, document: null, payment: null };
  }

  const job = normalizeJob(payload.job);
  if (job === null) throw new Error(MISSING_JOB);

  if (job.status === 'succeeded') {
    const document = normalizeDocument(payload.document);
    if (document === null) throw new Error(MISSING_DOCUMENT);
    return { status: 'ready', job, document, payment: null };
  }
  if (job.status === 'failed') {
    return { status: 'failed', job, document: null, payment: null };
  }
  return { status: 'running', job, document: null, payment: null };
}

/**
 * Последовательно опрашивает подготовку документа: следующий запрос планируется
 * только после ответа на предыдущий, а любой итог объявляется ровно один раз.
 */
export function startGenerationPolling({
  jobId,
  fetchStatus,
  onProgress,
  onReady,
  onFailed,
  onError,
  intervalMs = 2500,
  schedule = globalThis.setTimeout,
  cancelSchedule = globalThis.clearTimeout,
}) {
  const id = String(jobId || '').trim();
  if (!id) throw new Error('Не указана задача подготовки документа');
  const handlers = [fetchStatus, onProgress, onReady, onFailed, onError];
  if (handlers.some((handler) => typeof handler !== 'function')) {
    throw new Error('Проверка подготовки документа не настроена');
  }

  let stopped = false;
  let settled = false;
  let timer = null;

  const queue = () => {
    if (stopped || settled) return;
    timer = schedule(check, intervalMs);
  };

  const check = async () => {
    timer = null;
    try {
      const result = await fetchStatus(id);
      // Экран мог быть закрыт, пока запрос был в пути: обновлять его уже нельзя.
      if (stopped) return;
      const state = interpretGeneration(result);
      if (state.status === 'ready') {
        settled = true;
        // READY публикуется только после того, как interpretGeneration увидел
        // реальный filename сохранённого документа.
        publishLifecycle(state.job, state.document);
        onReady(state.document, state.job);
        return;
      }
      if (state.status === 'failed') {
        settled = true;
        publishLifecycle(state.job);
        onFailed(state.job);
        return;
      }
      if (state.job !== null) {
        publishLifecycle(state.job);
        onProgress(state.job);
      }
    } catch (error) {
      if (stopped) return;
      // Сетевой сбой — не приговор задаче: она продолжается на сервере.
      onError(error instanceof Error ? error : new Error(String(error || 'Ошибка проверки подготовки документа')));
    }
    queue();
  };

  queue();
  return () => {
    stopped = true;
    if (timer !== null) cancelSchedule(timer);
    timer = null;
  };
}
