/**
 * Созданное дело не создаётся второй раз из-за сбоя обновления списка.
 *
 * Создание шло цепочкой: создать дело, загрузить приложенные файлы, обновить
 * список дел, очистить черновик, открыть дело. Обновление списка стояло перед
 * очисткой черновика и переходом, поэтому его сбой — моргнувшая сеть, таймаут —
 * обрывал цепочку. Дело на сервере уже создано и файлы уже загружены, а
 * пользователь остаётся на форме, где нетронутым лежит его текст и приложенные
 * файлы, и читает сообщение об ошибке. Естественное действие — нажать «Создать
 * дело» ещё раз, и в списке появляется второе такое же дело с теми же
 * материалами.
 *
 * Создание подтверждает сервер, поэтому черновик очищается и дело открывается
 * сразу, а обновление списка становится тем, чем оно и было, — сверкой.
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

test('сбой обновления списка не отменяет созданное дело', () => {
  const handler = bodyOf('const createCase =');
  assert.ok(handler, 'создание дела не найдено');

  assert.doesNotMatch(
    handler,
    /await refreshCases\(\)/,
    'обновление списка снова стоит на пути результата создания',
  );
  assert.match(handler, /refreshCases\(\)\.catch\(/, 'список дел больше не сверяется с сервером');
});

test('черновик очищается и дело открывается раньше сверки со списком', () => {
  const handler = bodyOf('const createCase =');

  const cleared = handler.indexOf('clearLocalCaseData()');
  const opened = handler.indexOf("showScreen('case')");
  const refreshed = handler.indexOf('refreshCases(');
  assert.ok(cleared >= 0, 'черновик созданного дела не очищается');
  assert.ok(opened >= 0, 'созданное дело не открывается');
  assert.ok(refreshed >= 0, 'сверка со списком потеряна');

  assert.ok(cleared < refreshed, 'сбой сверки оставляет черновик, и дело создаётся второй раз');
  assert.ok(opened < refreshed, 'сбой сверки оставляет пользователя на форме создания');
});
