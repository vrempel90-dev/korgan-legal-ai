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
  assert.match(css, /position:\s*static/);
  assert.match(css, /width:\s*100%/);
  assert.match(css, /min-height:\s*52px/);
});

test('расчёты доступны только внутри формы искового заявления', () => {
  assert.match(bridge, /draft\?\.documentType\s*!==\s*'claim'/);
  assert.match(bridge, /main\.creation-page/);
  assert.match(bridge, /textarea\.case-input/);
  assert.match(bridge, /button\.style\.display\s*=\s*'none'/);
  assert.match(bridge, /insertAdjacentElement\('afterend', button\)/);
});

test('инструкция прямо объясняет куда попадёт рассчитанная сумма', () => {
  assert.match(bridge, /Под результатом нажмите «Добавить в иск»/);
  assert.match(bridge, /Сумма автоматически появится в поле с описанием иска/);
  assert.match(bridge, /проверьте текст и нажмите «Создать дело»/i);
});

test('госпошлина и неустойка добавляются в controlled textarea иска', () => {
  assert.match(bridge, /Рассчитанная госпошлина для иска/);
  assert.match(bridge, /Рассчитанная неустойка по статье 353 ГК РК/);
  assert.match(bridge, /new InputEvent\('input'/);
  assert.match(bridge, /textarea\.dispatchEvent\(event\)/);
  assert.match(bridge, /Добавить в иск/);
});

test('в claim-режиме панель сфокусирована на двух расчётах', () => {
  assert.match(css, /claim-calculators-mode \.korgan-legal-tool-card:last-of-type/);
  assert.match(css, /display:\s*none/);
});
