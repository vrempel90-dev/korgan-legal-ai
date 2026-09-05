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

/**
 * Ручной legacy-платёж опрашивается только после отправки чека. Tole нужно
 * опрашивать и до оплаты: webhook является быстрым сигналом, а этот GET —
 * резервная reconciliation-проверка durable payment intent у провайдера.
 */
export function shouldPollDocumentPayment(payment) {
  const status = String(payment?.status || '').trim();
  if (!status) return false;
  if (isAutomaticDocumentPayment(payment)) {
    // A confirmed payment can precede durable job creation. Keep reading until
    // the server returns the job; never send a second generation command.
    return ['pending_receipt', 'awaiting_admin', 'approved', 'consumed'].includes(status);
  }
  return status === 'awaiting_admin';
}

/**
 * Последовательно проверяет подтверждение оплаты. Следующий запрос планируется
 * только после ответа на предыдущий: ни Tole, ни legacy admin flow не получают
 * параллельные polling-запросы.
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
}) {
  const id = String(orderId || '').trim();
  if (!id) throw new Error('Не указан заказ для проверки оплаты');
  if (typeof fetchStatus !== 'function' || typeof onPayment !== 'function' || typeof onError !== 'function') {
    throw new Error('Проверка оплаты не настроена');
  }

  let stopped = false;
  let timer = null;

  const queue = () => {
    if (stopped) return;
    timer = schedule(check, intervalMs);
  };

  const check = async () => {
    timer = null;
    try {
      const result = await fetchStatus(id);
      if (stopped) return;
      const payment = requireDocumentPayment(result);
      if (String(payment.order_id || '') !== id) throw new Error('Получен статус другой оплаты');
      onPayment(payment);
      if (['approved', 'consumed'].includes(payment.status) && result.job && onGeneration) {
        if (result.job.case_id !== payment.case_id) throw new Error('Получен документ другого дела');
        await onGeneration(result);
        return;
      }
      // Older callers only consume payment state; keep their stop behaviour.
      if (!onGeneration && ['approved', 'consumed'].includes(payment.status)) return;
      if (!shouldPollDocumentPayment(payment)) return;
    } catch (error) {
      if (stopped) return;
      onError(error instanceof Error ? error : new Error(String(error || 'Ошибка проверки оплаты')));
    }
    queue();
  };

  if (immediate) check(); else queue();
  return () => {
    stopped = true;
    if (timer !== null) cancelSchedule(timer);
    timer = null;
  };
}
