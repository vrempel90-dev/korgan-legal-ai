/**
 * Ни один поставляемый скрипт не переписывает то, что показало приложение.
 *
 * Развёрнутое приложение (korgan.miniapp_api_recovery_cors) подключает слой
 * miniapp_manual_payment_admin, который отдаёт document_manual_confirmation:
 * true и automatic_receipt_verification: false и намеренно отключает клиентские
 * endpoint'ы приёма чека, «so no client can bypass the administrator decision».
 * Платёж сверяет человек. Скрипт, сообщающий пользователю, что чек проверяется
 * автоматически, говорит о его деньгах неправду.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');

/** Комментарий, объясняющий снятый приём, — не сам приём. */
const withoutComments = (code) =>
  code.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');

function shippedScripts() {
  const found = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      if (name === 'node_modules' || name === 'dist') continue;
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(js|jsx|mjs)$/.test(name)) continue;
      found.push([relative(miniapp, full).replace(/\\/g, '/'), readFileSync(full, 'utf8')]);
    }
  };
  walk(join(miniapp, 'src'));
  walk(join(miniapp, 'public'));
  return found;
}

test('ни один скрипт не подменяет отрисованный приложением текст', () => {
  /*
   * Обход текстовых узлов с заменой значений — второй владелец каждой надписи
   * в приложении. Пользователь видит не то, что отдал бэкенд, и расхождение
   * нигде не фиксируется. Запись nodeValue к тому же будит наблюдателя за
   * characterData, который эту же замену и запускает.
   */
  const offenders = shippedScripts()
    .filter(([, code]) => /\.nodeValue\s*=/.test(withoutComments(code)))
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('ни один скрипт не подменяет window.fetch', () => {
  // Подменённый fetch читает тела чужих ответов и меняет поведение всех
  // запросов приложения из места, о котором приложение не знает.
  const offenders = shippedScripts()
    .filter(([, code]) => /window\.fetch\s*=/.test(withoutComments(code)))
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('ни один скрипт не нажимает кнопку за пользователя по её надписи', () => {
  /*
   * Поиск кнопки по тексту и вызов click() запускал подготовку документа без
   * действия пользователя. Надпись — не идентификатор: перевод, перенос строки
   * или правка текста делают цель другой кнопкой.
   */
  const offenders = shippedScripts()
    .filter(([, code]) => {
      const clean = withoutComments(code);
      return /\.click\(\)/.test(clean) && /textContent/.test(clean);
    })
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('ни один скрипт не прячет разделы приложения вставленным стилем', () => {
  const offenders = shippedScripts()
    .filter(([, code]) => /display\s*:\s*none\s*!important/.test(withoutComments(code)))
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('ни один скрипт не следит за изменениями всего документа', () => {
  const offenders = shippedScripts()
    .filter(([, code]) => /new\s+MutationObserver/.test(withoutComments(code)))
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('фронтенд не обещает автоматическую проверку чека вместо сверки человеком', () => {
  /*
   * Развёрнутый бэкенд сверяет платёж администратором. Обещание автоматической
   * AI-проверки получателя, суммы, времени и номера операции — утверждение о
   * возможности, которой у продукта нет.
   */
  const claims = [/проверяет\s+чек\s+автоматически/i, /Автоматическая\s+AI-проверка/i];
  const offenders = shippedScripts()
    .filter(([, code]) => claims.some((claim) => claim.test(code)))
    .map(([name]) => name);

  assert.deepEqual(offenders, []);
});

test('страница не подключает снятый патч платёжного интерфейса', () => {
  const html = readFileSync(join(miniapp, 'index.html'), 'utf8');
  assert.ok(!html.includes('payment-auto-ui'), 'index.html всё ещё грузит патч платёжного интерфейса');
});
