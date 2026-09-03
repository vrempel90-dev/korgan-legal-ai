/**
 * После успешной загрузки материалов пользователь сразу продолжает путь
 * документа. Промежуточное сообщение «файлы обработаны» не должно задерживать
 * его на экране дела: состояние дела уже обновлено, список сверяется в фоне, а
 * следующий шаг — запрос подготовки/оплаты конкретного документа.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

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

test('после загрузки материалов сразу запускается платёжный путь документа', () => {
  const handler = bodyOf('const uploadMaterial =');

  const accepted = handler.indexOf('setActiveCase(latest)');
  const startPaymentFlow = handler.indexOf('await applyGenerationState(await korganApi.generateDocument(latest.id');
  assert.ok(accepted >= 0, 'результат загрузки не фиксируется в активном деле');
  assert.ok(startPaymentFlow >= 0, 'после загрузки материалов не запускается платёжный путь документа');
  assert.ok(accepted < startPaymentFlow, 'платёжный путь запускается до принятия загруженных материалов');
  assert.doesNotMatch(handler, /Обработано файлов/, 'лишнее промежуточное сообщение удерживает пользователя перед оплатой');
});

test('список дел всё же сверяется с сервером в фоне', () => {
  const handler = bodyOf('const uploadMaterial =');

  assert.match(handler, /refreshCases\(\)\.catch\(/, 'счётчик файлов в списке дел больше не обновляется');
  assert.doesNotMatch(handler, /await refreshCases\(\)/, 'сверка списка блокирует переход к оплате');
});
