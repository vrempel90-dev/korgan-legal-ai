/**
 * Нижняя панель не должна двигаться — ни при смене экрана, ни при генерации.
 *
 * Оболочка приложения (`Header`, `BottomNav`, `ConnectionBanner`, `Sources`)
 * объявлялась внутри `App`. Каждый рендер создавал новые типы компонентов, а
 * React для нового типа не обновляет узел, а размонтирует старый и монтирует
 * новый. Панель перерисовывалась целиком на каждом рендере — в том числе на
 * каждом тике прогресса генерации, который приходит несколько раз в секунду.
 * Именно это выглядело как дёрганье вкладок под пальцем.
 *
 * Вторая причина движения — панель была не на всех экранах. Переход
 * «дело → оплата → генерация → готово» её убирал и возвращал, и содержимое
 * прыгало на высоту панели.
 *
 * Поэтому здесь два условия сразу: типы компонентов постоянны (объявлены на
 * уровне модуля) и панель присутствует на каждом экране после согласия.
 * Экраны согласия — исключение: до принятия условий навигации нет.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
// Переводы строк приводятся к одному виду: на Windows git отдаёт в рабочую
// копию CRLF, и разбор по «\n}\n» переставал находить конец функции. Молча:
// indexOf возвращал -1, slice(0, -1) не падал, и тест считал кнопки соседних
// компонентов вместо панели. Проверка должна зависеть от разметки, а не от
// того, на какой системе сделан checkout.
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8').replace(/\r\n/g, '\n');

const SHELL = ['Header', 'BottomNav', 'ConnectionBanner', 'Sources'];

const appStart = app.indexOf('function App() {');
const moduleScope = app.slice(0, appStart);
const appBody = app.slice(appStart);

test('оболочка приложения объявлена на уровне модуля', () => {
  for (const name of SHELL) {
    assert.ok(
      moduleScope.includes(`function ${name}(`),
      `${name} должен быть объявлен до App, иначе React пересоздаёт его тип на каждом рендере`,
    );
  }
});

test('ни один компонент оболочки не создаётся заново внутри App', () => {
  for (const name of SHELL) {
    for (const form of [`function ${name}(`, `const ${name} =`, `let ${name} =`]) {
      assert.ok(
        !appBody.includes(form),
        `${name} объявлен внутри App (${form}) — панель будет размонтироваться на каждом рендере`,
      );
    }
  }
});

test('панель есть на каждом экране после согласия', () => {
  const screens = appBody.split('<div className="app-shell').slice(1);
  assert.ok(screens.length >= 10, 'экраны приложения не найдены — тест потерял связь с разметкой');

  for (const screen of screens) {
    const classes = screen.slice(0, screen.indexOf('>'));
    if (classes.includes('consent-shell')) {
      assert.ok(!screen.includes('{nav}'), 'до принятия условий навигации быть не должно');
      continue;
    }
    assert.ok(
      screen.includes('{nav}'),
      `экран "app-shell${classes}" остался без нижней панели — при переходе на него содержимое подпрыгнет`,
    );
  }
});

test('активная вкладка не меняет состав панели', () => {
  const start = moduleScope.indexOf('function BottomNav(');
  assert.notEqual(start, -1, 'BottomNav не найден — тест потерял связь с разметкой');
  const nav = moduleScope.slice(start);
  // Конец функции обязан найтись. Без этой проверки потерянный якорь не
  // проваливал тест, а расширял область до соседних компонентов, и кнопка
  // «повторить» из ConnectionBanner считалась шестой вкладкой.
  const end = nav.indexOf('\n}\n');
  assert.notEqual(end, -1, 'конец BottomNav не найден — тест потерял связь с разметкой');
  const body = nav.slice(0, end);
  const buttons = body.split('<button').length - 1;
  assert.equal(buttons, 5, 'набор вкладок должен быть фиксированным на всех экранах');
  assert.ok(
    !/\{\s*\w+\s*&&\s*<button/.test(body),
    'вкладка не должна появляться или исчезать по условию — меняется только класс active',
  );
});
