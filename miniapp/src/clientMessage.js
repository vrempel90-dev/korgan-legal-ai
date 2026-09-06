/**
 * Текст ошибки, который допустимо показать клиенту.
 *
 * Ответ сервера — не готовая фраза для экрана. Служебные `detail` англоязычны
 * («Case not found», «Document not generated»), а некоторые выносят наружу
 * внутренние имена («KORGAN generator unavailable: …»). Полезные сообщения
 * сервер тоже присылает, и они написаны на языке клиента, поэтому граница
 * проходит по языку, а не по коду ответа: написанное человеку показывается,
 * служебная строка заменяется собственной формулировкой.
 */

const HUMAN_TEXT = /[Ѐ-ӿ]/;
const INTERNAL_TEXT = /\b(?:Tole|webhook|traceback|stack trace|RuntimeError|SQL|UUID|payment_intent|provider_status|verification_notes|quality_issues|NEEDS_VERIFICATION|FILING_ACTION|SENIOR_PREFLIGHT|API[_ -]?KEY|source-bound|KORGAN[ _]+(?:API|QA|QUALITY)|PRELIMINARY DRAFT|LAWYER-REVIEW DRAFT)\b|\b[a-z]+(?:_[a-z]+){2,}\b/i;

export function clientDocumentNotes(notes) {
  return Array.isArray(notes) ? notes.filter(note => typeof note === 'string' && HUMAN_TEXT.test(note) && !INTERNAL_TEXT.test(note)) : [];
}

/** Обрыв связи и истёкшее ожидание: следующая попытка может пройти. */
const TRANSIENT_CODES = new Set(['KORGAN_API_NETWORK_ERROR', 'KORGAN_API_TIMEOUT']);

/**
 * Диагностика уходит в консоль, а не на экран.
 *
 * Раньше любое исключение превращалось в одну фразу «Сервис временно
 * недоступен», и вместе с текстом исчезала причина: по жалобе клиента нельзя
 * было сказать, отказал ли сервер, оборвалась ли связь или запрос ушёл не туда.
 * Пользовательских данных здесь нет — только код ответа и код ошибки.
 */
function reportForDiagnostics(error) {
  if (!error) return;
  const status = error.status ? ` status=${error.status}` : '';
  const code = error.code ? ` code=${error.code}` : '';
  try {
    console.warn(`KORGAN API request failed${status}${code}`);
  } catch {
    // Консоли может не быть — это не повод ронять экран.
  }
}

export function clientMessage(error, texts) {
  // Отказ в подписи Telegram повтором не лечится: экран объясняет это сам.
  if (error?.code === 'KORGAN_API_UNAUTHORIZED') return texts.sessionExpired;

  const served = String(error?.message || '');
  if (HUMAN_TEXT.test(served) && !INTERNAL_TEXT.test(served)) return served;

  reportForDiagnostics(error);
  if (error?.status === 404) return texts.notFound;
  // Обрыв связи — не отказ сервиса. Называть его отказом значит сообщать
  // пользователю, что работа не идёт, тогда как она продолжается на сервере, а
  // клиент просто не дозвонился.
  if (TRANSIENT_CODES.has(error?.code) && texts.connectionLost) return texts.connectionLost;
  return texts.down;
}
