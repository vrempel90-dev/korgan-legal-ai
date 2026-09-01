/**
 * Переход на «Мои дела» происходит сразу, а не после ответа сервера.
 *
 * Оба входа в список дел — нижняя навигация и плитка на главной — сначала
 * дожидались `refreshCases()` и только потом меняли экран. Пока запрос был в
 * пути, нажатие не давало ничего: ни отклика (тактильный отклик живёт внутри
 * `go`), ни смены экрана, ни индикатора занятости — эти кнопки его не
 * показывают. На медленной связи это выглядит зависанием, человек нажимает
 * ещё раз, а на разорванной связи экран открывается только после того, как
 * запрос упадёт по таймауту.
 *
 * Список дел уже умеет обновляться сам по себе: `refreshCases()` защищён
 * поколением действия, поэтому опоздавший ответ ничего не перезапишет.
 * Значит, экран показывается сразу, а обновление списка догоняет.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

const entries = app
  .split('\n')
  .filter(line => line.includes("go('cases')") && line.includes('refreshCases()'));

test('оба входа в список дел обновляют его вместе с переходом', () => {
  assert.equal(entries.length, 2, 'входов в «Мои дела» с обновлением списка должно быть два');
});

test('экран списка дел показывается до запроса, а не после него', () => {
  for (const line of entries) {
    assert.ok(
      line.indexOf("go('cases')") < line.indexOf('refreshCases()'),
      'переход выполняется только после ответа сервера — нажатие остаётся без отклика',
    );
  }
});

test('переход на список дел не ждёт сетевой запрос', () => {
  assert.doesNotMatch(
    app,
    /await refreshCases\(\);[^\n]{0,32}go\('cases'\)/,
    'навигация заблокирована ожиданием ответа сервера',
  );
});
