/**
 * Визуальный контракт шапки зафиксирован по последнему снимку MiniApp до
 * 2026-08-31 06:00 Asia/Almaty (commit 78d2384).
 *
 * В том дизайне постоянная шапка KORGAN собиралась из двух CSS-псевдоэлементов:
 * отдельной буквы «K» и подписи «| KORGAN» в Georgia. При этом настоящий
 * public/korgan-wordmark.svg продолжал использоваться на экране согласия,
 * в hero и как фоновый водяной знак. Эти проверки намеренно фиксируют именно
 * тот визуальный контракт, не затрагивая lifecycle, delivery или legal runtime.
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

test('шапка сохраняет композицию KORGAN из снимка 31 августа', () => {
  const shell = topbarRules.find(
    rule => rule.includes('width:188px') && rule.includes('background:none'),
  );
  assert.ok(shell, 'размер или фон шапки отличаются от снимка 31 августа');
});

test('шапка сохраняет текстовую KORGAN-композицию снимка 31 августа', () => {
  const letter = topbarRules.find(
    rule => rule.includes('::before') && rule.includes('content:"K"') && rule.includes('Georgia'),
  );
  const word = topbarRules.find(
    rule => rule.includes('::after') && rule.includes('content:"| KORGAN"') && rule.includes('Georgia'),
  );
  assert.ok(letter, 'в шапке отсутствует буква K из снимка 31 августа');
  assert.ok(word, 'в шапке отсутствует подпись | KORGAN из снимка 31 августа');
});

test('вордмарк действительно поставляется для остальных элементов бренда', () => {
  const url = brand.match(/--korgan-wordmark\s*:\s*url\(['"]?([^'\")]+)/);
  assert.ok(url, 'переменная --korgan-wordmark не объявлена');
  assert.ok(
    brand.includes('.consent-page .brand-mark.large') &&
      brand.includes('background:var(--korgan-wordmark)'),
    'экран согласия больше не использует фирменный вордмарк',
  );
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
