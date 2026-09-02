const PAYMENT_PENDING = new Set(['created', 'pending', 'pending_receipt', 'awaiting_admin']);
const PAYMENT_REJECTED = new Set(['rejected', 'failed', 'expired', 'cancelled']);
const GENERATION_ACTIVE = new Set(['queued', 'running']);

const LABELS = {
  ru: {
    case_created: 'Дело создано',
    materials_ready: 'Материалы загружены',
    payment_required: 'Требуется оплата',
    payment_pending: 'Ожидается подтверждение оплаты',
    payment_failed: 'Оплата не подтверждена',
    paid: 'Оплата подтверждена',
    queued: 'Документ поставлен в очередь',
    running: 'Документ готовится',
    failed: 'Подготовка не завершилась',
    ready: 'Документ готов',
  },
  kk: {
    case_created: 'Іс құрылды',
    materials_ready: 'Материалдар жүктелді',
    payment_required: 'Төлем қажет',
    payment_pending: 'Төлем расталуын күтеміз',
    payment_failed: 'Төлем расталмады',
    paid: 'Төлем расталды',
    queued: 'Құжат кезекке қойылды',
    running: 'Құжат дайындалып жатыр',
    failed: 'Құжат дайындау аяқталмады',
    ready: 'Құжат дайын',
  },
};

/**
 * Один канонический взгляд на состояние дела.
 *
 * Функция ничего не переводит сама: она только проектирует уже подтверждённые
 * backend-состояния в один клиентский статус. Приоритет важен — сохранённый
 * документ сильнее старого payment state, а фактический failed job сильнее
 * статуса дела, который мог обновиться позже.
 */
export function projectCaseLifecycle({ caseData, payment = null, generation = null, document = null } = {}) {
  const item = caseData && typeof caseData === 'object' ? caseData : {};
  const paymentStatus = String(payment?.status || '').trim();
  const generationStatus = String(generation?.status || '').trim();
  const hasStoredDocument = Boolean(
    String(document?.filename || item.filename || '').trim()
      && (document?.status === 'document_ready' || item.status === 'document_ready' || item.has_document === true),
  );

  if (hasStoredDocument) return 'ready';
  if (generationStatus === 'failed') return 'failed';
  if (GENERATION_ACTIVE.has(generationStatus)) return generationStatus;
  if (paymentStatus === 'approved' || paymentStatus === 'paid' || paymentStatus === 'consumed') return 'paid';
  if (PAYMENT_REJECTED.has(paymentStatus)) return 'payment_failed';
  if (PAYMENT_PENDING.has(paymentStatus)) return 'payment_pending';
  if (payment?.payment_required === true) return 'payment_required';
  if (item.status === 'materials_ready' || Number(item.materials_count || 0) > 0) return 'materials_ready';
  return 'case_created';
}

export function lifecycleLabel(status, language = 'ru') {
  const locale = language === 'kk' ? 'kk' : 'ru';
  return LABELS[locale][status] || LABELS[locale].case_created;
}

export function isTerminalLifecycle(status) {
  return status === 'ready' || status === 'failed' || status === 'payment_failed';
}
