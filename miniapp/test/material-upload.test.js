/**
 * Загруженные материалы не объявляются незагруженными.
 *
 * Загрузка шла цепочкой: отправить файлы, обновить список дел, сообщить
 * «Обработано файлов: N». Обновление списка стояло между отправкой и
 * сообщением, поэтому его сбой уводил обработчик в общий разбор ошибок — и
 * пользователь получал сообщение о неудаче по загрузке, которая прошла:
 * материалы на сервере, счётчик файлов на экране дела уже вырос, а под ним
 * висит красное предупреждение. Повторная загрузка тех же файлов — прямое
 * следствие такого сообщения.
 *
 * Список дел на экране дела не показан, поэтому его обновление ничего не
 * решает и уходит за результат загрузки.
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

test('сбой обновления списка не выдаётся за сбой загрузки', () => {
  const handler = bodyOf('const uploadMaterial =');
  assert.ok(handler, 'загрузка материалов не найдена');

  assert.doesNotMatch(
    handler,
    /await refreshCases\(\)/,
    'обновление списка снова стоит на пути результата загрузки',
  );
});

test('результат загрузки сообщается раньше сверки со списком', () => {
  const handler = bodyOf('const uploadMaterial =');

  const reported = handler.indexOf('Обработано файлов');
  const refreshed = handler.indexOf('refreshCases(');
  assert.ok(reported >= 0, 'результат загрузки не сообщается');
  assert.ok(refreshed >= 0, 'сверка со списком потеряна');
  assert.ok(reported < refreshed, 'сбой сверки снова отменяет сообщение об успешной загрузке');
});

test('список дел всё же сверяется с сервером', () => {
  const handler = bodyOf('const uploadMaterial =');

  assert.match(handler, /refreshCases\(\)\.catch\(/, 'счётчик файлов в списке дел больше не обновляется');
});
