/**
 * Удалённое дело исчезает из списка, даже если обновление списка не дошло.
 *
 * Удаление шло одной цепочкой: удалить на сервере → перечитать список →
 * перейти к списку. Перечитывание стояло посередине, и его сбой — моргнувшая
 * сеть, таймаут, пустой ответ — обрывал цепочку до перехода. Дело на сервере
 * при этом уже удалено, а в списке осталась его карточка: нажатие на неё
 * отвечало «дело не найдено», и пользователь видел дело, которого нет.
 *
 * Удаление подтверждено ответом сервера, поэтому карточка убирается сразу и
 * своими силами, а перечитывание списка становится тем, чем оно и было —
 * уточнением: его сбой больше ничего не решает.
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

test('удалённое дело убирается из списка без похода в сеть', () => {
  const handler = bodyOf('const deleteCurrentCase =');
  assert.ok(handler, 'удаление дела не найдено');

  assert.match(
    handler,
    /setCases\(prev => prev\.filter\(/,
    'список дел не очищается от удалённого дела своими силами',
  );
  assert.match(
    handler,
    /latestCases\.current\.invalidate\(\)/,
    'ушедшее обновление списка вернёт удалённое дело обратно',
  );
});

test('переход к списку не зависит от успеха обновления', () => {
  const handler = bodyOf('const deleteCurrentCase =');

  assert.match(handler, /showScreen\('cases'\)/, 'после удаления пользователь остаётся на удалённом деле');
  assert.doesNotMatch(
    handler,
    /await refreshCases\(\)/,
    'сбой обновления списка снова обрывает удаление до перехода',
  );
});

test('список всё же пересобирается с сервера', () => {
  const handler = bodyOf('const deleteCurrentCase =');

  assert.match(
    handler,
    /refreshCases\(\)\.catch\(/,
    'после удаления список больше не сверяется с сервером',
  );
});
