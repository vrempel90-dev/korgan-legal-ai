import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const src = join(miniapp, 'src');
const index = readFileSync(join(miniapp, 'index.html'), 'utf8');
const bridge = readFileSync(join(src, 'claimLegalCalculators.js'), 'utf8');
const css = readFileSync(join(src, 'claim-legal-calculators.css'), 'utf8');

test('кнопка расчётов подключается после существующего legal workspace', () => {
  assert.match(index, /\/src\/claim-legal-calculators\.css/);
  assert.match(index, /\/src\/claimLegalCalculators\.js/);
  assert.ok(index.indexOf('/src/claimLegalCalculators.js') > index.indexOf('/src/legalWorkspaceUi.js'));
});

test('клиент видит профессиональное название без технического Юр. инструменты', () => {
  assert.match(bridge, /Расчёт госпошлины и неустойки/);
  assert.doesNotMatch(bridge, /Юр\. инструменты/);
  assert.match(css, /position:\s*absolute/);
  assert.match(css, /min-height:\s*52px/);
  assert.match(css, /claim-calculator-active/);
});

test('расчёты доступны только внутри формы искового заявления', () => {
  assert.match(bridge, /draft\?\.documentType\s*!==\s*'claim'/);
  assert.match(bridge, /main\.creation-page/);
  assert.match(bridge, /textarea\.case-input/);
  assert.match(bridge, /classList\.remove\(ACTIVE_CLASS\)/);
  assert.match(bridge, /classList\.add\(ACTIVE_CLASS\)/);
  assert.match(css, /body:not\(\.claim-calculator-active\) #korgan-legal-tools-button/);
});

test('launcher остаётся вне disposable React subtree и только визуально привязан к форме', () => {
  assert.doesNotMatch(bridge, /insertAdjacentElement\('afterend', button\)/);
  assert.match(bridge, /getBoundingClientRect\(\)/);
  assert.match(bridge, /--claim-calc-left/);
  assert.match(bridge, /--claim-calc-top/);
  assert.match(bridge, /--claim-calc-width/);
});

test('инструкция прямо объясняет куда попадёт рассчитанная сумма', () => {
  assert.match(bridge, /Под результатом нажмите «Добавить в иск»/);
  assert.match(bridge, /Сумма автоматически появится в поле с описанием иска/);
  assert.match(bridge, /проверьте текст и нажмите «Создать дело»/i);
});

test('инструкция обновляется вместе с RU KK языком приложения', () => {
  assert.match(bridge, /article\.dataset\.language\s*=\s*lang/);
  assert.match(bridge, /existingGuide\.dataset\.language\s*!==\s*lang/);
  assert.match(bridge, /existingGuide\.replaceWith\(guide\(copy, lang\)\)/);
  assert.match(bridge, /Қалай пайдалану керек/);
});

test('госпошлина и неустойка добавляются в controlled textarea иска', () => {
  assert.match(bridge, /Рассчитанная госпошлина для иска/);
  assert.match(bridge, /Рассчитанная неустойка по статье 353 ГК РК/);
  assert.match(bridge, /new InputEvent\('input'/);
  assert.match(bridge, /textarea\.dispatchEvent\(event\)/);
  assert.match(bridge, /Добавить в иск/);
});

test('повторный расчёт заменяет старую сумму того же типа, а не дублирует её', () => {
  assert.match(bridge, /const CALCULATION_LINE\s*=\s*\{/);
  assert.match(bridge, /function upsertClaimCalculation/);
  assert.match(bridge, /current\.replace\(pattern, line\)/);
  assert.match(bridge, /appendToClaim\(line, kind\)/);
  assert.match(bridge, /duty:\s*\/\^\(\?:Рассчитанная госпошлина/);
  assert.match(bridge, /penalty:\s*\/\^\(\?:Рассчитанная неустойка/);
});

test('период неустойки фиксируется в момент запуска расчёта', () => {
  assert.match(bridge, /const submitted\s*=\s*\{/);
  assert.match(bridge, /start:\s*document\.getElementById\('klt-penalty-start'\)/);
  assert.match(bridge, /end:\s*document\.getElementById\('klt-penalty-end'\)/);
  assert.match(bridge, /waitForCalculation\('penalty', submitted\)/);
  assert.match(bridge, /formatDate\(submitted\.start\)/);
  assert.match(bridge, /formatDate\(submitted\.end\)/);
});

test('в claim-режиме панель сфокусирована на двух расчётах', () => {
  assert.match(css, /claim-calculators-mode \.korgan-legal-tool-card:last-of-type/);
  assert.match(css, /display:\s*none/);
});
