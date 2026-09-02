import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const index = readFileSync(join(here, '..', 'index.html'), 'utf8');
const preferences = readFileSync(join(src, 'ui-preferences.css'), 'utf8');
const visible = readFileSync(join(src, 'visible-nav.css'), 'utf8');

test('нижняя панель показывает ровно три глобальных назначения', () => {
  assert.match(preferences, /grid-template-columns:\s*repeat\(3,/);
  assert.match(preferences, /button:nth-child\(2\)[\s\S]*button:nth-child\(3\)[\s\S]*display:\s*none\s*!important/);
});

test('скрытые Дела и AI-юрист подсвечивают видимую Главную', () => {
  assert.match(visible, /nth-child\(2\)\.active[\s\S]*nth-child\(1\)/);
  assert.match(visible, /nth-child\(3\)\.active[\s\S]*nth-child\(1\)/);
});

test('внутренний экран без прямой вкладки оставляет Главную активной', () => {
  assert.match(visible, /bottom-nav:not\(:has\(> button\.active\)\)[\s\S]*nth-child\(1\)/);
});

test('visible-nav contract не перехватывает клики и не блокирует навигацию', () => {
  assert.doesNotMatch(visible, /pointer-events\s*:/);
  assert.doesNotMatch(visible, /display\s*:\s*none/);
  assert.doesNotMatch(visible, /position\s*:\s*(fixed|absolute)/);
});

test('visible-nav загружается после базового правила трёх вкладок', () => {
  const base = index.indexOf('/src/ui-preferences.css');
  const contract = index.indexOf('/src/visible-nav.css');
  assert.ok(base >= 0, 'ui-preferences.css не подключён');
  assert.ok(contract > base, 'visible-nav.css должен загружаться после ui-preferences.css');
});
