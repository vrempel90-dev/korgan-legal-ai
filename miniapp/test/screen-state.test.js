/**
 * Показанный экран обязан совпадать с тем, куда пользователя отправили.
 *
 * Экраны выбирались цепочкой проверок вида `screen === 'doc-payment' &&
 * docPayment`. Когда данных не оказывалось, ни одна ветка не срабатывала и
 * отрисовывалась последняя — главная. Пользователь видел главную, но нижняя
 * навигация не подсвечивала ни одной вкладки, потому что состояние по-прежнему
 * называлось `doc-payment`: экран и состояние расходились, и ни ошибки, ни
 * объяснения при этом не показывалось.
 *
 * Достаточно одного неполного ответа сервера — об оплате или о подготовке, —
 * чтобы это увидел живой клиент. Здесь проверяется, что экран выбирается по
 * состоянию, которое у клиента действительно есть, и что подмена всегда ведёт
 * к осмысленному экрану, а не к главной без вкладки.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveScreen } from '../src/screenState.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

const FULL = {
  hasCase: true,
  hasPayment: true,
  hasGeneration: true,
  hasDocument: true,
};

test('экран с полными данными показывается как есть', () => {
  for (const screen of ['home', 'documents', 'new-case', 'case', 'chat', 'doc-payment', 'generating', 'ready', 'cases', 'help', 'profile', 'admin-payments']) {
    assert.equal(resolveScreen(screen, FULL), screen);
  }
});

test('оплата без данных оплаты возвращает к делу, а не к главной', () => {
  assert.equal(resolveScreen('doc-payment', { ...FULL, hasPayment: false }), 'case');
});

test('подготовка без задачи возвращает к делу, а не к главной', () => {
  assert.equal(resolveScreen('generating', { ...FULL, hasGeneration: false }), 'case');
});

test('экран выпуска без документа не выдаёт готовность', () => {
  assert.equal(resolveScreen('ready', { ...FULL, hasDocument: false }), 'case');
});

test('дело без открытого дела показывает список дел', () => {
  assert.equal(resolveScreen('case', { ...FULL, hasCase: false }), 'cases');
});

test('без открытого дела подмена доходит до списка дел', () => {
  const empty = { hasCase: false, hasPayment: false, hasGeneration: false, hasDocument: false };
  assert.equal(resolveScreen('doc-payment', empty), 'cases');
  assert.equal(resolveScreen('generating', empty), 'cases');
  assert.equal(resolveScreen('ready', empty), 'cases');
});

test('неизвестное состояние показывает главную', () => {
  assert.equal(resolveScreen('', FULL), 'home');
  assert.equal(resolveScreen('unknown-screen', FULL), 'home');
  assert.equal(resolveScreen(undefined, FULL), 'home');
});

test('приложение рисует и подсвечивает один и тот же экран', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');

  assert.match(app, /resolveScreen\(/, 'main.jsx выбирает экран без общего правила');
  assert.ok(
    !/screen === 'doc-payment' && docPayment/.test(app),
    'экран оплаты всё ещё проваливается на главную при неполных данных',
  );
  assert.ok(
    !/screen === 'generating' && generation/.test(app),
    'экран подготовки всё ещё проваливается на главную при неполных данных',
  );
  assert.ok(
    !/screen === '/.test(app),
    'решение об отрисовке и подсветке принимается по разным источникам состояния',
  );
});
