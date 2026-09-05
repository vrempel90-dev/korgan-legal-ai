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

export function clientMessage(error, texts) {
  // Отказ в подписи Telegram повтором не лечится: экран объясняет это сам.
  if (error?.code === 'KORGAN_API_UNAUTHORIZED') return texts.sessionExpired;

  const served = String(error?.message || '');
  if (HUMAN_TEXT.test(served) && !INTERNAL_TEXT.test(served)) return served;
  if (error?.status === 404) return texts.notFound;
  return texts.down;
}
