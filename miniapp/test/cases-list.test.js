/**
 * «Мои дела» показывают то, что есть на сервере сейчас, а не то, что было.
 *
 * Список перечитывался из шести мест сразу — нижняя навигация, плитка на
 * главной, создание дела, загрузка материалов, готовый документ, удаление, — и
 * ни одно из них не проверяло, что его ответ ещё нужен. Запросы уходили
 * параллельно, а `setCases` выполнял тот, чей ответ пришёл последним.
 *
 * Отсюда удалённое дело возвращалось в список: нажатие на вкладку «Дела»
 * отправляло запрос, пользователь успевал удалить дело, а пришедший следом
 * старый ответ возвращал его на экран. Нажатие на такое дело давало «Дело не
 * найдено» — фантом, который нечем открыть. Тот же порядок ответов после
 * удаления всех данных возвращал в список все дела разом.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('список дел заполняется только самым свежим ответом', () => {
  const refresh = app.slice(app.indexOf('const refreshCases'), app.indexOf('const applyDocument'));

  assert.match(refresh, /\.start\(\)/, 'перечитывание списка не отслеживает свою актуальность');
  assert.ok(
    /if \(!\w+\(\)\)/.test(refresh),
    'ответ устаревшего запроса всё ещё заполняет список дел',
  );
});

test('ни один экран не запрашивает список дел мимо общего правила', () => {
  // Прямой вызов listCases в обработчике кнопки — это ещё один ответ, который
  // никто не проверяет на актуальность.
  const outside = app.slice(app.indexOf('const applyDocument'));

  assert.doesNotMatch(outside, /korganApi\.listCases/, 'список дел запрашивается в обход перечитывания');
});

test('удаление всех данных обесценивает уже отправленные запросы списка', () => {
  const wipe = app.slice(app.indexOf('const deleteAllData'), app.indexOf('const loadAdminOrders'));

  assert.match(
    wipe,
    /\.invalidate\(\)/,
    'ответ запроса, отправленного до удаления, вернёт все дела обратно',
  );
});
