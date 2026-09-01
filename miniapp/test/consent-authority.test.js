/**
 * localStorage не является источником согласия: оно могло быть отозвано в
 * другом WebView, а версия условий могла измениться.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { resolveConsent } from '../src/consentAuthority.js';

const miniapp = join(dirname(fileURLToPath(import.meta.url)), '..');

test('серверное согласие текущей версии открывает приложение', () => {
  assert.deepEqual(
    resolveConsent({ accepted: true, terms_version: '2026-08-16-v1' }, '2026-08-16-v1'),
    { accepted: true, reason: 'accepted' },
  );
});

test('отзыв на сервере закрывает приложение независимо от localStorage', () => {
  assert.deepEqual(
    resolveConsent({ accepted: false, terms_version: '2026-08-16-v1' }, '2026-08-16-v1'),
    { accepted: false, reason: 'not_accepted' },
  );
});

test('старая версия согласия требует принять новые условия', () => {
  assert.deepEqual(
    resolveConsent({ accepted: true, terms_version: '2025-01-01-v1' }, '2026-08-16-v1'),
    { accepted: false, reason: 'version_mismatch' },
  );
});

test('неполный ответ не превращается в согласие', () => {
  assert.throws(() => resolveConsent({ accepted: true }, '2026-08-16-v1'), /статус согласия/i);
  assert.throws(() => resolveConsent(null, '2026-08-16-v1'), /статус согласия/i);
});

test('запуск не принимает условия автоматически', () => {
  const source = readFileSync(join(miniapp, 'src', 'main.jsx'), 'utf8');
  const boot = source.slice(source.indexOf('const boot = async'), source.indexOf('const acceptTerms = async'));

  assert.doesNotMatch(boot, /korganApi\.acceptConsent\(TERMS_VERSION\)/);
  assert.match(boot, /korganApi\.consentStatus\(\)/);
});
