/**
 * Созданное дело не создаётся второй раз и сразу продолжает путь документа.
 *
 * После подтверждённого сервером создания/загрузки материалов пользователь не
 * должен попадать на промежуточный экран дела и повторно нажимать
 * «Подготовить документ». Черновик очищается, сверка списка идёт в фоне, а
 * клиент сразу запрашивает состояние подготовки: при включённой оплате это
 * открывает экран оплаты.
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

test('после ввода данных сразу открывается платёжный путь документа', () => {
  const handler = bodyOf('const createCase =');

  const cleared = handler.indexOf('clearLocalCaseData()');
  const startPaymentFlow = handler.indexOf('await applyGenerationState(await korganApi.generateDocument(item.id');
  const refreshed = handler.indexOf('refreshCases(');

  assert.ok(cleared >= 0, 'черновик созданного дела не очищается');
  assert.ok(startPaymentFlow >= 0, 'после создания дела не запускается платёжный путь документа');
  assert.ok(refreshed >= 0, 'сверка со списком потеряна');
  assert.doesNotMatch(handler, /showScreen\('case'\)/, 'пользователь снова попадает на лишний промежуточный экран дела');
  assert.ok(cleared < startPaymentFlow, 'платёжный путь запускается до фиксации результата создания');
  assert.doesNotMatch(handler, /await refreshCases\(\)/, 'сверка списка блокирует переход к оплате');
});
