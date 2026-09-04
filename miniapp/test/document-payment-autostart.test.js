import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { shouldAutostartPaidGeneration } from '../src/documentPaymentAutostart.js';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');


test('русская подтверждённая оплата сразу открывает генерацию', () => {
  assert.equal(shouldAutostartPaidGeneration({
    approved: true,
    heading: 'Оплата подтверждена',
    label: 'Подготовить оплаченный документ',
  }), true);
});


test('казахская подтверждённая оплата сразу открывает генерацию', () => {
  assert.equal(shouldAutostartPaidGeneration({
    approved: true,
    heading: 'Төлем расталды',
    label: 'Төленген құжатты дайындау',
  }), true);
});


test('обычная подготовка до оплаты не перехватывается', () => {
  assert.equal(shouldAutostartPaidGeneration({
    approved: false,
    heading: 'Оплата документа',
    label: 'Подготовить документ',
  }), false);
});


test('disabled-кнопка не запускается повторно', () => {
  assert.equal(shouldAutostartPaidGeneration({
    approved: true,
    heading: 'Оплата подтверждена',
    label: 'Подготовить оплаченный документ',
    disabled: true,
  }), false);
});


test('autostart загружается раньше основного React-приложения', () => {
  const html = readFileSync(join(miniapp, 'index.html'), 'utf8');
  const autostart = html.indexOf('/src/documentPaymentAutostart.js');
  const main = html.indexOf('/src/main.jsx');
  assert.ok(autostart >= 0);
  assert.ok(main >= 0);
  assert.ok(autostart < main);
});
