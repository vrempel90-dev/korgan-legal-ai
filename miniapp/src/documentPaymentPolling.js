/**
 * Достаёт из ответа сервера статус оплаты или отказывается его признавать.
 *
 * Ответ без статуса нельзя класть в состояние экрана: экран оплаты перестаёт
 * рисоваться, а пользователь оказывается неизвестно где и без объяснения.
 */
export function requireDocumentPayment(result) {
  const payment = result?.payment;
  if (!payment || typeof payment.status !== 'string' || !payment.status.trim()) {
    throw new Error('Получен неполный статус оплаты');
  }
  return payment;
}

/** Tole подтверждает банковский факт сервер-сервер, без чека пользователя. */
export function isAutomaticDocumentPayment(payment) {
  return payment?.payment_provider === 'tole' || payment?.automatic_confirmation === true;
}

/** Подтверждённый заказ больше никогда не должен возвращать экран к оплате. */
export function isConfirmedDocumentPayment(payment) {
  const status = String(payment?.status || '').trim();
  return status === 'approved' || status === 'consumed';
}

/**
 * Ручной legacy-платёж опрашивается после отправки чека. Tole нужно опрашивать
 * и до оплаты: webhook является быстрым сигналом, а GET — резервной сверкой.
 *
 * После подтверждения любой провайдер остаётся в polling до появления durable
 * generation job. Это закрывает короткое окно "оплата уже approved, задача ещё
 * не видна" и не отправляет вторую команду генерации.
 */
export function shouldPollDocumentPayment(payment) {
  const status = String(payment?.status || '').trim();
  if (!status) return false;
  if (isAutomaticDocumentPayment(payment)) {
    return ['pending_receipt', 'awaiting_admin', 'approved', 'consumed'].includes(status);
  }
  return ['awaiting_admin', 'approved', 'consumed'].includes(status);
}

/**
 * Последовательно проверяет подтверждение оплаты. Следующий запрос планируется
 * только после ответа на предыдущий: параллельных polling-запросов нет.
 *
 * При возврате из внешнего банковского приложения visibilitychange запускает
 * одну немедленную сверку вместо ожидания следующего 3-секундного тика. In-flight
 * guard не позволяет возврату создать второй одновременный запрос.
 */
export function startDocumentPaymentPolling({
  orderId,
  fetchStatus,
  onPayment,
  onGeneration,
  onError,
  intervalMs = 3000,
  immediate = false,
  schedule = globalThis.setTimeout,
  cancelSchedule = globalThis.clearTimeout,
  visibilityTarget = globalThis.document,
}) {
  const id = String(orderId || '').trim();
  if (!id) throw new Error('Не указан заказ для проверки оплаты');
  if (typeof fetchStatus !== 'function' || typeof onPayment !== 'function' || typeof onError !== 'function') {
    throw new Error('Проверка оплаты не настроена');
  }

  let stopped = false;
  let timer = null;
  let checking = false;

  const clearTimer = () => {
    if (timer !== null) cancelSchedule(timer);
    timer = null;
  };

  const queue = () => {
    if (stopped || checking || timer !== null) return;
    timer = schedule(check, intervalMs);
  };

  const check = async () => {
    if (stopped || checking) return;
    checking = true;
    clearTimer();
    let keepPolling = true;

    try {
      const result = await fetchStatus(id);
      if (stopped) return;
      const payment = requireDocumentPayment(result);
      if (String(payment.order_id || '') !== id) throw new Error('Получен статус другой оплаты');
      onPayment(payment);

      if (isConfirmedDocumentPayment(payment) && result.job && onGeneration) {
        if (result.job.case_id !== payment.case_id) throw new Error('Получен документ другого дела');
        await onGeneration(result);
        keepPolling = false;
        return;
      }

      // Старые callers используют только состояние оплаты и после подтверждения
      // должны остановиться, как раньше.
      if (!onGeneration && isConfirmedDocumentPayment(payment)) {
        keepPolling = false;
        return;
      }

      keepPolling = shouldPollDocumentPayment(payment);
    } catch (error) {
      if (stopped) return;
      onError(error instanceof Error ? error : new Error(String(error || 'Ошибка проверки оплаты')));
      keepPolling = true;
    } finally {
      checking = false;
      if (!stopped && keepPolling) queue();
    }
  };

  const onVisible = () => {
    if (stopped || visibilityTarget?.hidden) return;
    clearTimer();
    void check();
  };

  if (visibilityTarget && typeof visibilityTarget.addEventListener === 'function') {
    visibilityTarget.addEventListener('visibilitychange', onVisible);
  }

  if (immediate) void check(); else queue();
  return () => {
    stopped = true;
    clearTimer();
    if (visibilityTarget && typeof visibilityTarget.removeEventListener === 'function') {
      visibilityTarget.removeEventListener('visibilitychange', onVisible);
    }
  };
}
