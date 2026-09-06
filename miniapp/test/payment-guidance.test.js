import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('automatic document payment shows explanatory copy without changing the payment action', () => {
  assert.match(source, /После успешной оплаты система автоматически подтвердит платёж и приступит к подготовке документа\. Обычно это занимает несколько минут\./);
  assert.match(source, /automaticPending && paymentUrl/);
  assert.match(source, /window\.open\(paymentUrl, '_blank', 'noopener,noreferrer'\)/);
  assert.match(source, /className="payment-guidance"/);
  assert.match(source, /\{t\.automaticPaymentText\}/);
});

test('manual receipt payment path remains present and separate', () => {
  assert.match(source, /!automatic && !approved && !awaiting/);
  assert.match(source, /receipt-upload/);
  assert.match(source, /uploadDocReceipt/);
});
