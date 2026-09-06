import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'src', 'documentPaymentPolling.js'), 'utf8');

test('polling has visibility resume hook and in-flight guard', () => {
  assert.match(source, /visibilitychange/);
  assert.match(source, /checking/);
  assert.match(source, /approved/);
  assert.match(source, /consumed/);
});
