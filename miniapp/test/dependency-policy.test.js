import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const miniapp = join(dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(join(miniapp, 'package.json'), 'utf8'));
const lock = JSON.parse(readFileSync(join(miniapp, 'package-lock.json'), 'utf8'));

test('production-сборка не зависит от плавающего latest', () => {
  const floating = Object.entries(manifest.dependencies || {})
    .filter(([, range]) => range === 'latest' || range === '*' || /[xX]/.test(range));

  assert.deepEqual(floating, []);
});

test('манифест и lock-файл фиксируют одни версии корневых зависимостей', () => {
  assert.deepEqual(lock.packages[''].dependencies, manifest.dependencies);

  for (const [name, version] of Object.entries(manifest.dependencies || {})) {
    assert.equal(lock.packages[`node_modules/${name}`]?.version, version, `${name} не зафиксирован версией ${version}`);
  }
});
