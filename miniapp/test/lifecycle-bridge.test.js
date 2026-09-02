import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const index = readFileSync(join(root, 'index.html'), 'utf8');
const bridge = readFileSync(join(root, 'src', 'lifecycleBridge.js'), 'utf8');
const generation = readFileSync(join(root, 'src', 'generationJob.js'), 'utf8');

test('lifecycle sidecar загружается отдельно от React UI', () => {
  assert.match(index, /src="\/src\/lifecycleBridge\.js"/);
  assert.match(index, /src="\/src\/main\.jsx"/);
  assert.ok(index.indexOf('lifecycleBridge.js') < index.indexOf('main.jsx'));
});

test('sidecar не манипулирует DOM и не меняет дизайн KORGAN', () => {
  assert.doesNotMatch(bridge, /querySelector|createElement|innerHTML|classList|MutationObserver/);
  assert.match(bridge, /playLifecycleFeedback/);
});

test('событие READY публикуется после проверки реального документа', () => {
  const ready = generation.slice(generation.indexOf("if (state.status === 'ready')"), generation.indexOf("if (state.status === 'failed')"));
  assert.match(ready, /publishLifecycle\(state\.job, state\.document\)/);
  assert.match(generation, /filename/);
});
