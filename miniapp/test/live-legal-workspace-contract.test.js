import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const src = join(miniapp, 'src');

const index = readFileSync(join(miniapp, 'index.html'), 'utf8');
const ui = readFileSync(join(src, 'legalWorkspaceUi.js'), 'utf8');
const css = readFileSync(join(src, 'legal-workspace.css'), 'utf8');

test('live MiniApp подключает Legal Workspace поверх существующего UI', () => {
  assert.match(index, /\/src\/approved-compat\.css/);
  assert.match(index, /\/src\/legal-workspace\.css/);
  assert.match(index, /\/src\/main\.jsx/);
  assert.match(index, /\/src\/legalWorkspaceUi\.js/);
  assert.ok(index.indexOf('/src/legal-workspace.css') > index.indexOf('/src/approved-compat.css'));
  assert.ok(index.indexOf('/src/legalWorkspaceUi.js') > index.indexOf('/src/main.jsx'));
});

test('live Legal Workspace использует только новые legal-workspace API и не включает оплату', () => {
  assert.match(ui, /\/miniapp\/legal-workspace\/state-duty/);
  assert.match(ui, /\/miniapp\/legal-workspace\/late-penalty-353/);
  assert.match(ui, /\/miniapp\/legal-workspace\/stress-test/);
  assert.doesNotMatch(ui, /PAYMENTS_ENABLED/);
  assert.doesNotMatch(ui, /\/payments\//);
});

test('Stress Test берёт язык из сохранённого языка приложения', () => {
  assert.match(ui, /korgan-miniapp-state-v1/);
  assert.match(ui, /language:\s*selectedLanguage\(\)/);
  assert.doesNotMatch(ui, /document\.documentElement\.lang/);
});

test('ответы юридических инструментов вставляются как текст, а не как HTML', () => {
  assert.match(ui, /box\.textContent\s*=\s*text/);
  assert.doesNotMatch(ui, /box\.innerHTML\s*=\s*text/);
});

test('панель Legal Workspace не скрывает и не заменяет существующий интерфейс', () => {
  assert.match(css, /korgan-legal-tools-button/);
  assert.match(css, /korgan-legal-tools-backdrop/);
  assert.doesNotMatch(css, /#root\s*\{[^}]*display\s*:\s*none/);
});
