import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const main = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('Tole document payment exposes a link and hides receipt controls', () => {
  assert.match(main, /const automatic = isAutomaticDocumentPayment\(docPayment\)/);
  assert.match(main, /const paymentUrl = safeUrl\(docPayment\.payment_url \|\| docPayment\.kaspi_url\)/);
  assert.match(main, /automaticPending && paymentUrl/);
  assert.match(main, /!automatic && !approved && !awaiting/);
});

test('Tole payment screen says confirmation is automatic', () => {
  assert.match(main, /Tole автоматически подтвердит платёж/);
  assert.match(main, /чек загружать не нужно/);
  assert.match(main, /automaticPaymentSecurity/);
});

test('approved Tole payment auto-starts the existing generation path once', () => {
  assert.match(main, /autoStartedPayment = useRef\(''\)/);
  assert.match(main, /docPayment\?\.status === 'approved'/);
  assert.match(main, /autoStartedPayment\.current = approvedOrder;\s*generateDocument\(\)/);
});

test('deferred global generation progress UI remains present and untouched', () => {
  assert.match(main, /if \(view === 'generating'\)/);
  assert.match(main, /role="progressbar"/);
});
