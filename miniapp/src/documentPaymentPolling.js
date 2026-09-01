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

/**
 * Последовательно проверяет решение администратора по оплате документа.
 * Следующий запрос планируется только после ответа на предыдущий.
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
      if (payment.status !== 'awaiting_admin') return;
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
