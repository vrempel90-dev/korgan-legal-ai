/**
 * Решённая оплата уходит из очереди сверки, даже если список не перечитался.
 *
 * Экран ручной сверки показывает только заказы в состоянии `awaiting_admin`,
 * и решённый заказ исчезал из него единственным способом — перечитыванием
 * списка с сервера. Перечитывание гасит свои ошибки само: при сбое сети список
 * оставался прежним, и подтверждённая оплата продолжала висеть в очереди.
 *
 * Для оператора это худший из возможных обманов: он видит нерешённый заказ,
 * которого нет, и подтверждает или отклоняет его повторно — по платежу,
 * решение по которому уже принято.
 *
 * Решение подтверждает сервер, поэтому заказ убирается из очереди сразу, а
 * перечитывание остаётся сверкой с сервером и ничего больше не решает.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

/** Тело обработчика: объявление и всё до закрывающей его строки. */
const bodyOf = declaration => {
  const start = app.indexOf(declaration);
  if (start < 0) return '';
  const end = app.indexOf('\n  };', start);
  return app.slice(start, end < 0 ? start : end);
};

test('решённый заказ убирается из очереди своими силами', () => {
  const handler = bodyOf('const decideAdminOrder =');
  assert.ok(handler, 'решение по оплате не найдено');

  assert.match(
    handler,
    /setAdminOrders\(prev => prev\.filter\(/,
    'решённый заказ уходит из очереди только через перечитывание списка',
  );
});

test('заказ уходит из очереди раньше, чем начинается перечитывание', () => {
  const handler = bodyOf('const decideAdminOrder =');

  const removal = handler.indexOf('setAdminOrders(prev => prev.filter(');
  const reload = handler.indexOf('loadAdminOrders()');
  assert.ok(removal >= 0 && reload >= 0, 'в решении нет очистки очереди или сверки с сервером');
  assert.ok(
    removal < reload,
    'сбой перечитывания снова оставляет решённый заказ в очереди',
  );
});

test('очередь всё же сверяется с сервером', () => {
  const handler = bodyOf('const decideAdminOrder =');

  assert.match(handler, /loadAdminOrders\(\)/, 'после решения очередь больше не сверяется с сервером');
});
