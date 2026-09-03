import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

function read(name) {
  return readFileSync(join(src, name), 'utf8');
}

test('консультация по готовому документу перечитывает текущий revision дела', () => {
  const ui = read('documentConsultationUi.js');
  const api = read('korganApi.js');
  assert.match(ui, /Консультация по документу:/);
  assert.match(api, /\/miniapp\/cases\/\$\{encodeURIComponent\(id\)\}/);
  assert.match(api, /result\?\.case\?\.document_revision/);
  assert.match(api, /document_revision:\s*documentRevision\s*\|\|\s*null/);
});

test('Stress Test берёт язык из сохранённого языка приложения', () => {
  const code = read('legalWorkspaceUi.js');
  assert.match(code, /korgan-miniapp-state-v1/);
  assert.match(code, /function selectedLanguage/);
  assert.match(code, /const language = selectedLanguage\(\)/);
  assert.match(code, /body:\s*JSON\.stringify\(\{[^}]*language\s*\}\)/s);
  assert.doesNotMatch(code, /document\.documentElement\.lang\s*===\s*['"]kk['"]/);
});

test('выключенный звук и вибрация реально доходят до lifecycle feedback', () => {
  const bridge = read('lifecycleBridge.js');
  const feedback = read('lifecycleFeedback.js');
  assert.match(bridge, /isSoundEnabled/);
  assert.match(bridge, /isVibrationEnabled/);
  assert.match(bridge, /soundEnabled:\s*isSoundEnabled\(storage\)/);
  assert.match(bridge, /vibrationEnabled:\s*isVibrationEnabled\(storage\)/);
  assert.match(feedback, /soundEnabled\s*=\s*true/);
  assert.match(feedback, /vibrationEnabled\s*=\s*true/);
  assert.match(feedback, /if \(vibrationEnabled\) telegramFeedback/);
  assert.match(feedback, /!soundEnabled/);
});

test('обычные navigation haptics также уважают настройку вибрации', () => {
  const telegram = read('telegram.js');
  assert.match(telegram, /import \{ isVibrationEnabled \}/);
  assert.match(telegram, /if \(!isVibrationEnabled\(\)\) return/);
});
