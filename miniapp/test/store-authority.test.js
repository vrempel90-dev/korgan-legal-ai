/**
 * Browser storage хранит только удобства интерфейса. Решение о согласии живёт на
 * сервере и не должно переживать там как второй, противоречащий источник истины.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { loadState, saveDraft } from '../src/store.js';

const miniapp = join(dirname(fileURLToPath(import.meta.url)), '..');

function memoryStorage(initial = null) {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_key, next) => { value = next; },
    removeItem: () => { value = null; },
    value: () => value,
  };
}

test('legacy local consent удаляется при чтении состояния', () => {
  const previous = globalThis.localStorage;
  globalThis.localStorage = memoryStorage(JSON.stringify({
    language: 'kk',
    consentAccepted: true,
    consentVersion: '2025-01-01-v1',
    draft: { documentType: 'claim', description: 'Факты' },
  }));
  try {
    const state = loadState();
    assert.equal(state.language, 'kk');
    assert.deepEqual(state.draft, { documentType: 'claim', description: 'Факты' });
    assert.equal('consentAccepted' in state, false);
    assert.equal('consentVersion' in state, false);
  } finally {
    globalThis.localStorage = previous;
  }
});

test('следующая запись физически очищает legacy consent из localStorage', () => {
  const previous = globalThis.localStorage;
  const storage = memoryStorage(JSON.stringify({
    language: 'ru',
    consentAccepted: true,
    consentVersion: '2026-08-16-v1',
    draft: { documentType: null, description: '' },
  }));
  globalThis.localStorage = storage;
  try {
    saveDraft({ description: 'Новые факты' });
    const persisted = JSON.parse(storage.value());
    assert.equal(persisted.draft.description, 'Новые факты');
    assert.equal('consentAccepted' in persisted, false);
    assert.equal('consentVersion' in persisted, false);
  } finally {
    globalThis.localStorage = previous;
  }
});

test('локальное хранилище не экспортирует принятие или отзыв согласия', () => {
  const source = readFileSync(join(miniapp, 'src', 'store.js'), 'utf8');
  assert.doesNotMatch(source, /export function (?:acceptConsent|revokeConsent)/);
  assert.doesNotMatch(source, /consentAccepted|consentVersion/);
});

test('ошибка startup показывает повтор вместо вечного spinner', () => {
  const source = readFileSync(join(miniapp, 'src', 'main.jsx'), 'utf8');
  const bootstrapScreen = source.slice(
    source.indexOf('if (consent === null)'),
    source.indexOf('if (!consent)'),
  );

  assert.match(bootstrapScreen, /connection === 'down'/);
  assert.match(bootstrapScreen, /onClick=\{boot\}/);
  assert.match(bootstrapScreen, /t\.retry/);
});
