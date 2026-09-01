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

export function clientMessage(error, texts) {
  // Отказ в подписи Telegram повтором не лечится: экран объясняет это сам.
  if (error?.code === 'KORGAN_API_UNAUTHORIZED') return texts.sessionExpired;

  const served = String(error?.message || '');
  if (HUMAN_TEXT.test(served)) return served;
  if (error?.status === 404) return texts.notFound;
  return texts.down;
}
