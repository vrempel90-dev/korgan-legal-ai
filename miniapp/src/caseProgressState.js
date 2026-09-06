import { interpretGeneration } from './generationJob.js';

const COPY = {
  ru: {
    idle: 'Подготовка не начата',
    payment: 'Ожидает оплату',
    ready: 'Документ готов',
    failed: 'Подготовка не завершена',
    unavailable: 'Статус временно недоступен',
    queued: 'Дело принято в работу',
    starting: 'Подготавливаю материалы',
    legal_research: 'Проверяю право и источники',
    quality_control: 'Проверяю факты и качество',
    document_render: 'Формирую документ Word',
    completed: 'Документ готов',
    interrupted: 'Подготовка прервана',
  },
  kk: {
    idle: 'Дайындау басталған жоқ',
    payment: 'Төлем күтілуде',
    ready: 'Құжат дайын',
    failed: 'Дайындау аяқталмады',
    unavailable: 'Мәртебе уақытша қолжетімсіз',
    queued: 'Іс жұмысқа қабылданды',
    starting: 'Материалдар дайындалуда',
    legal_research: 'Құқық пен дереккөздер тексерілуде',
    quality_control: 'Фактілер мен сапа тексерілуде',
    document_render: 'Word құжаты жасалуда',
    completed: 'Құжат дайын',
    interrupted: 'Дайындау үзілді',
  },
};

function copy(language) {
  return COPY[language === 'kk' ? 'kk' : 'ru'];
}

function clampProgress(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

/**
 * Состояния, дальше которых дело не меняется. Опрашивать их бессмысленно, а
 * показывать над ними полоску подготовки — значит утверждать, что работа идёт.
 */
export const TERMINAL_KINDS = new Set(['ready', 'failed', 'idle', 'payment']);

export function caseProgressSnapshot(result, language = 'ru') {
  const t = copy(language);
  let state;
  try {
    state = interpretGeneration(result);
  } catch {
    // Непонятный ответ — это неизвестность, а не «идёт подготовка». Опрос
    // здесь допускается, но конечное число раз: сколько именно, решает
    // вызывающий, у которого есть счётчик неудач по делу.
    return { kind: 'unavailable', progress: null, label: t.unavailable, poll: true, terminal: false };
  }

  if (state.status === 'idle') {
    return { kind: 'idle', progress: 0, label: t.idle, poll: false, terminal: true };
  }
  if (state.status === 'payment_required') {
    return { kind: 'payment', progress: 0, label: t.payment, poll: false, terminal: true };
  }
  if (state.status === 'ready') {
    return { kind: 'ready', progress: 100, label: t.ready, poll: false, terminal: true };
  }
  if (state.status === 'failed') {
    return {
      kind: 'failed',
      progress: clampProgress(state.job?.progress),
      label: t.failed,
      poll: false,
      terminal: true,
    };
  }

  const stage = String(state.job?.stage || '').trim();
  return {
    kind: 'running',
    progress: clampProgress(state.job?.progress),
    label: t[stage] || t.starting,
    poll: true,
    terminal: false,
  };
}
