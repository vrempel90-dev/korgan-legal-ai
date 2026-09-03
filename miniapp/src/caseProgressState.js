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

export function caseProgressSnapshot(result, language = 'ru') {
  const t = copy(language);
  let state;
  try {
    state = interpretGeneration(result);
  } catch {
    return { kind: 'unavailable', progress: null, label: t.unavailable, poll: true };
  }

  if (state.status === 'idle') {
    return { kind: 'idle', progress: 0, label: t.idle, poll: false };
  }
  if (state.status === 'payment_required') {
    return { kind: 'payment', progress: 0, label: t.payment, poll: false };
  }
  if (state.status === 'ready') {
    return { kind: 'ready', progress: 100, label: t.ready, poll: false };
  }
  if (state.status === 'failed') {
    return {
      kind: 'failed',
      progress: clampProgress(state.job?.progress),
      label: t.failed,
      poll: false,
    };
  }

  const stage = String(state.job?.stage || '').trim();
  return {
    kind: 'running',
    progress: clampProgress(state.job?.progress),
    label: t[stage] || t.starting,
    poll: true,
  };
}
