/**
 * Один источник правды о том, какой экран показан.
 *
 * Экран выбирался цепочкой условий, где у части веток к имени экрана было
 * дописано наличие данных. Когда данных не оказывалось — неполный ответ об
 * оплате, потерянная задача подготовки, — не срабатывала ни одна ветка, и
 * рисовалась последняя, главная. При этом состояние по-прежнему называлось
 * прежним экраном, поэтому нижняя навигация не подсвечивала ничего, а
 * пользователю никто ничего не объяснял.
 *
 * Здесь имя экрана и данные для него сводятся к одному ответу: что показать.
 * Экран без своих данных заменяется ближайшим осмысленным, а не главной.
 */

const SELF_SUFFICIENT = new Set([
  'home',
  'documents',
  'new-case',
  'chat',
  'cases',
  'help',
  'profile',
  'admin-payments',
]);

// Чем экран обеспечен: пока это условие не выполнено, показывать его нечем.
const REQUIRES = {
  case: state => state.hasCase,
  'doc-payment': state => state.hasCase && state.hasPayment,
  generating: state => state.hasCase && state.hasGeneration,
  ready: state => state.hasCase && state.hasDocument,
};

/**
 * Возвращает экран, который действительно будет показан.
 *
 * @param {string} screen запрошенное состояние навигации
 * @param {{hasCase?: boolean, hasPayment?: boolean, hasGeneration?: boolean, hasDocument?: boolean}} available
 */
export function resolveScreen(screen, available = {}) {
  const name = String(screen || '');
  const state = {
    hasCase: available.hasCase === true,
    hasPayment: available.hasPayment === true,
    hasGeneration: available.hasGeneration === true,
    hasDocument: available.hasDocument === true,
  };

  if (SELF_SUFFICIENT.has(name)) return name;
  const requirement = REQUIRES[name];
  if (requirement === undefined) return 'home';
  if (requirement(state)) return name;
  // Работа велась по делу, поэтому возврат к делу — ближайшее честное место.
  // Без открытого дела остаётся список дел: он объясняет, что происходит,
  // тогда как главная выглядела бы так, будто ничего и не запускали.
  return state.hasCase ? 'case' : 'cases';
}
