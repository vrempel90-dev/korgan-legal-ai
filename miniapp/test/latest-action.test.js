/**
 * Ответ на действие применяется, только если пользователь всё ещё его ждёт.
 *
 * Открытие дела ничем не защищено: список дел не гасит свои кнопки, а сам
 * обработчик не отказывался стартовать, пока идёт предыдущее открытие. Нажатие
 * на дело A, а через секунду на дело B давало два запроса; вернувшийся позже
 * ответ A перезаписывал открытое дело, и на экране дела B оказывались чужие
 * материалы. Тот же обработчик после ответа сервера переключал экран на
 * подготовку документа — даже если пользователь к тому моменту уже ушёл на
 * другую вкладку и его выдёргивало обратно.
 *
 * Здесь проверяется общее правило: у действия есть поколение, и всё, что
 * пришло из устаревшего поколения, молча отбрасывается.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createLatestAction } from '../src/latestAction.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

test('только что начатое действие остаётся актуальным', () => {
  const actions = createLatestAction();

  const current = actions.start();

  assert.equal(current(), true);
});

test('новое действие делает предыдущее неактуальным', () => {
  const actions = createLatestAction();

  const first = actions.start();
  const second = actions.start();

  assert.equal(first(), false, 'ответ первого действия всё ещё применился бы');
  assert.equal(second(), true);
});

test('уход с экрана обесценивает идущее действие', () => {
  const actions = createLatestAction();

  const current = actions.start();
  actions.invalidate();

  assert.equal(current(), false, 'ответ догнал пользователя на другом экране');
});

test('из очереди нажатий актуально ровно одно — последнее', () => {
  const actions = createLatestAction();

  const taps = [actions.start(), actions.start(), actions.start()];

  assert.deepEqual(taps.map(tap => tap()), [false, false, true]);
});

test('открытие дела не запускается поверх уже идущего', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  const openCase = app.slice(app.indexOf('const openCase'), app.indexOf('const uploadMaterial'));

  assert.match(openCase, /if \(busy\) return;/, 'второе нажатие запускает второй запрос за делом');
});

test('восстановленная подготовка не выдёргивает пользователя с другого экрана', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  const openCase = app.slice(app.indexOf('const openCase'), app.indexOf('const uploadMaterial'));

  assert.match(openCase, /createLatestAction|latestCase/, 'открытие дела не отслеживает свою актуальность');
  assert.ok(
    /if \(!\w+\(\)\) return;/.test(openCase),
    'ответ устаревшего открытия дела всё ещё меняет экран',
  );
});

test('повторное нажатие не запускает второе необратимое действие', () => {
  const app = readFileSync(join(src, 'main.jsx'), 'utf8');
  const guarded = {
    refreshDocPayment: app.slice(app.indexOf('const refreshDocPayment'), app.indexOf('const deliverActiveDocument')),
    deleteCurrentCase: app.slice(app.indexOf('const deleteCurrentCase'), app.indexOf('const deleteAllData')),
    deleteAllData: app.slice(app.indexOf('const deleteAllData'), app.indexOf('const loadAdminOrders')),
  };

  for (const [name, body] of Object.entries(guarded)) {
    assert.match(body, /busy\) return/, `${name} запускается повторно поверх идущего`);
  }
});
