/**
 * Уведомление живёт ровно столько, сколько экран, на котором оно возникло.
 *
 * Сообщение гасилось только в `go` — переходе по нажатию. Все остальные
 * переходы меняли экран напрямую: готовый документ, требование оплаты, начало
 * подготовки, открытие дела, удаление дела и данных. Поэтому временная ошибка
 * опроса («сервис недоступен») оставалась на экране и после того, как документ
 * благополучно подготовился: под заголовком «документ готов» висело красное
 * предупреждение о недоступности, относящееся к уже пережитому сбою.
 *
 * Одно событие — одно уведомление: смена экрана гасит сообщение предыдущего
 * всегда, каким бы способом переход ни произошёл.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const app = readFileSync(join(src, 'main.jsx'), 'utf8');

test('смена экрана гасит уведомление предыдущего', () => {
  assert.match(
    app,
    /const showScreen = next => \{ setNotice\(''\); setScreen\(next\); \};/,
    'у смены экрана нет общего перехода, который гасит уведомление',
  );
});

test('ни один переход не меняет экран в обход общего правила', () => {
  const direct = app.match(/setScreen\(/g) || [];

  assert.equal(
    direct.length,
    1,
    'экран меняется мимо общего перехода, и уведомление переживает свой экран',
  );
});

test('готовый документ показывается без предупреждения прошлого экрана', () => {
  const apply = app.slice(app.indexOf('const applyDocument'), app.indexOf('const applyGenerationState'));

  assert.match(apply, /showScreen\('ready'\)/, 'экран готовности открывается мимо общего перехода');
});

test('требование оплаты и начало подготовки тоже приходят чистыми', () => {
  const apply = app.slice(app.indexOf('const applyGenerationState'), app.indexOf('const chooseDocument'));

  assert.match(apply, /showScreen\('doc-payment'\)/, 'экран оплаты открывается мимо общего перехода');
  assert.match(apply, /showScreen\('generating'\)/, 'экран подготовки открывается мимо общего перехода');
});
