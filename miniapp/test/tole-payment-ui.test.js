// Contract tests for the client-visible document payment flow. No provider or AI calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const main = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('automatic document payment exposes a link and hides receipt controls', () => {
  assert.match(main, /const automatic = isAutomaticDocumentPayment\(docPayment\)/);
  assert.match(main, /const paymentUrl = safeUrl\(docPayment\.payment_url \|\| docPayment\.kaspi_url\)/);
  assert.match(main, /automaticPending && paymentUrl/);
  assert.match(main, /!automatic && !approved && !awaiting/);
});

test('payment screen does not expose provider or technical confirmation mechanics', () => {
  assert.doesNotMatch(main, /Tole автоматически подтвердит платёж/);
  assert.doesNotMatch(main, /TOLE · SECURITY/);
  assert.doesNotMatch(main, /KORGAN PREPAY/);
  assert.match(main, /documentPaymentText: 'Оплатите документ через Kaspi\.'/);
});

test('approved automatic payment auto-starts the existing generation path once', () => {
  assert.match(main, /autoStartedPayment = useRef\(''\)/);
  assert.match(main, /docPayment\?\.status === 'approved'/);
  assert.match(main, /autoStartedPayment\.current = approvedOrder;\s*generateDocument\(\)/);
});

test('deferred global generation progress UI remains present and untouched', () => {
  assert.match(main, /if \(view === 'generating'\)/);
  assert.match(main, /role="progressbar"/);
});
