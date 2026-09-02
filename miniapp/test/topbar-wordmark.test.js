import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const css = readFileSync(join(miniapp, 'src', 'approved-compat.css'), 'utf8');

test('верхняя шапка использует настоящий K | KORGAN wordmark', () => {
  assert.match(css, /\.topbar \.brand-mark\s*\{[\s\S]*korgan-wordmark\.svg/);
  assert.match(css, /\.topbar \.brand-mark > svg\s*\{[\s\S]*display:\s*none/);
  assert.match(css, /\.topbar \.brand\s*\{[\s\S]*display:\s*none/);
  assert.ok(existsSync(join(miniapp, 'public', 'korgan-wordmark.svg')));
});
