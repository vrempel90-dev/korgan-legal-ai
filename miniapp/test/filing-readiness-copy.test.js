/**
 * Автоматические quality gates не заменяют финальную проверку юристом.
 * Клиент не вправе называть AI-документ готовым к подаче.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const miniapp = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(join(miniapp, 'src', 'main.jsx'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/(^|[^:])\/\/.*$/gm, '$1');

test('AI-документ не называется готовым к подаче', () => {
  assert.doesNotMatch(source, /['"`](?:Готов к подаче|Беруге дайын)['"`]/i);
});

test('положительный статус требует финальной проверки юристом на обоих языках', () => {
  assert.match(source, /Готов к финальной проверке юристом/);
  assert.match(source, /Заңгердің қорытынды тексеруіне дайын/);
});

test('пройденные автоматические проверки не выдаются за человеческую проверку', () => {
  assert.match(source, /Автоматические проверки пройдены\. Перед использованием документ должен проверить юрист\./);
  assert.match(source, /Автоматты тексерулер аяқталды\. Пайдаланар алдында құжатты заңгер тексеруі тиіс\./);
});
