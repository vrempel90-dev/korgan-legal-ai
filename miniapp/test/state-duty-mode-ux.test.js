import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const index = readFileSync(join(here, '..', 'index.html'), 'utf8');
const code = readFileSync(join(src, 'stateDutyModeUx.js'), 'utf8');

test('state-duty mode UX is shipped in the Telegram MiniApp bundle', () => {
  assert.match(index, /\/src\/stateDutyModeUx\.js/);
});

test('property mode suppresses irrelevant nonproperty count before submit', () => {
  assert.match(code, /const usesAmount = mode === 'property' \|\| mode === 'mixed'/);
  assert.match(code, /const usesNonproperty = mode === 'nonproperty' \|\| mode === 'mixed'/);
  assert.match(code, /if \(!usesNonproperty\) \{\s*nonproperty\.value = '0'/s);
  assert.match(code, /if \(id === 'klt-duty-submit'\) syncStateDutyMode\(\)/);
  assert.match(code, /document\.addEventListener\('click',[\s\S]*, true\)/);
});

test('nonproperty and mixed modes require at least one nonproperty demand', () => {
  assert.match(code, /nonproperty\.min = '1'/);
  assert.match(code, /if \(!Number\.isFinite\(value\) \|\| value < 1\) nonproperty\.value = '1'/);
  assert.match(code, /nonproperty\.required = usesNonproperty/);
});

test('irrelevant property amount is cleared for nonproperty mode', () => {
  assert.match(code, /if \(!usesAmount\) amount\.value = ''/);
  assert.match(code, /amount\.required = usesAmount/);
});
