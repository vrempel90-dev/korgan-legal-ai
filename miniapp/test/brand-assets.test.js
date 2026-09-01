/**
 * Логотип в шапке — утверждённый файл, а не набранный шрифтом текст.
 *
 * Вордмарк KORGAN лежит в public/korgan-wordmark.svg и подставляется через
 * переменную --korgan-wordmark: так он выглядит одинаково на экране согласия,
 * в водяном знаке фона и в шапке. Позже шапку перевели на реконструкцию
 * средствами CSS — псевдоэлементы с буквой «K» и текстом «| KORGAN», набранные
 * Georgia. Это уже не логотип, а его пересказ: пропорции, засечки и кернинг
 * зависят от того, какой шрифт нашёлся на устройстве, а на экране согласия
 * рядом продолжал жить настоящий знак. Шапка — единственное место, где логотип
 * виден постоянно, поэтому подмена была заметнее всего.
 *
 * Здесь проверяется, что шапка берёт тот же файл, что и остальные места, и что
 * файл действительно поставляется.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const brand = readFileSync(join(miniapp, 'src', 'korgan-brand.css'), 'utf8');
const html = readFileSync(join(miniapp, 'index.html'), 'utf8');

const topbarRules = brand
  .split('\n')
  .flatMap(line => line.split('}'))
  .filter(rule => rule.includes('.topbar .brand-mark'));

test('шапка показывает вордмарк из файла', () => {
  const painted = topbarRules.filter(rule => rule.includes('--korgan-wordmark'));
  assert.ok(painted.length > 0, 'в шапке не осталось ссылки на --korgan-wordmark');
});

test('шапка не набирает логотип шрифтом', () => {
  for (const rule of topbarRules) {
    assert.ok(
      !/content\s*:\s*["'][^"']*K/.test(rule),
      `логотип в шапке подменён текстом: ${rule.trim().slice(0, 80)}`,
    );
  }
});

test('вордмарк действительно поставляется', () => {
  const url = brand.match(/--korgan-wordmark\s*:\s*url\(['"]?([^'")]+)/);
  assert.ok(url, 'переменная --korgan-wordmark не объявлена');
  const file = join(miniapp, 'public', url[1].replace(/^\//, ''));
  assert.ok(existsSync(file), `${url[1]} не найден в public/`);
  assert.ok(readFileSync(file, 'utf8').includes('<svg'), 'вордмарк не является SVG');
});

test('страница не подключает удалённые таблицы стилей', () => {
  for (const [, href] of html.matchAll(/<link[^>]+href="(\/src\/[^"]+\.css)"/g)) {
    assert.ok(
      existsSync(join(miniapp, href.replace(/^\//, ''))),
      `index.html ссылается на отсутствующий ${href}`,
    );
  }
});
