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
    return status === 'pending_receipt' || status === 'awaiting_admin';
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
  onError,
  intervalMs = 8000,
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
      onPayment(payment);
      if (!shouldPollDocumentPayment(payment)) return;
    } catch (error) {
      if (stopped) return;
      onError(error instanceof Error ? error : new Error(String(error || 'Ошибка проверки оплаты')));
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
