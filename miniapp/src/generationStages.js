/**
 * Шаги подготовки документа — те же, что отмечает бэкенд.
 *
 * Экран показывает список стадий, а не одну полосу, потому что подготовка
 * занимает около двух минут: без списка человек не отличает идущую работу от
 * зависшей. Список строится по стадии, которую сообщил сервер, и ничего не
 * досочиняет: шаг становится пройденным только после того, как о следующем
 * сообщил бэкенд. Таймера, дорисовывающего проценты, здесь нет намеренно —
 * он врёт ровно в тот момент, когда работа встала.
 */

/** Порядок стадий совпадает с korgan/generation_progress.py::STAGE_ORDER. */
export const STAGE_ORDER = [
  'starting',
  'legal_research',
  'drafting',
  'legal_qa',
  'document_render',
  'delivery',
];

const STAGE_LABELS = {
  ru: {
    starting: 'Материалы дела получены',
    legal_research: 'Проверяем законодательство Казахстана',
    drafting: 'Формируем документ',
    legal_qa: 'Расчёты и финальная юридическая проверка',
    document_render: 'Готовим файл Word',
    delivery: 'Сохраняем документ',
  },
  kk: {
    starting: 'Іс материалдары алынды',
    legal_research: 'Қазақстан заңнамасы тексерілуде',
    drafting: 'Құжат қалыптастырылуда',
    legal_qa: 'Есептеулер және қорытынды құқықтық тексеру',
    document_render: 'Word файлы дайындалуда',
    delivery: 'Құжат сақталуда',
  },
};

/** Стадии до начала работы и после её конца в список шагов не входят. */
const TERMINAL_DONE = new Set(['completed']);
const NOT_STARTED = new Set(['queued', '']);

/**
 * Состояние каждого шага: `done`, `active`, `failed` или `pending`.
 *
 * Сбой не отменяет уже пройденных шагов: работа действительно дошла до той
 * стадии, на которой оборвалась, и скрывать это значит терять единственную
 * подсказку о том, где именно сломалось.
 */
export function generationSteps(job, language = 'ru') {
  const labels = STAGE_LABELS[language] || STAGE_LABELS.ru;
  const stage = String(job?.stage || '');
  const failed = String(job?.status || '') === 'failed';
  const finished = TERMINAL_DONE.has(stage) || String(job?.status || '') === 'succeeded';
  const current = NOT_STARTED.has(stage) ? -1 : STAGE_ORDER.indexOf(stage);

  return STAGE_ORDER.map((id, index) => {
    let state = 'pending';
    if (finished) state = 'done';
    else if (current < 0) state = 'pending';
    else if (index < current) state = 'done';
    else if (index === current) state = failed ? 'failed' : 'active';
    return { id, label: labels[id] || id, state };
  });
}
