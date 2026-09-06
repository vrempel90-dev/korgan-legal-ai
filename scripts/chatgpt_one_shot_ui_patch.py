from pathlib import Path

main_path = Path('miniapp/src/main.jsx')
main = main_path.read_text(encoding='utf-8')

ru_old = "automaticPayment: 'Оплата документа', automaticPaymentText: 'Оплатите документ через Kaspi.', automaticPaymentSecurity: '',"
ru_new = "automaticPayment: 'Оплата документа', automaticPaymentText: 'После успешной оплаты система автоматически подтвердит платёж и приступит к подготовке документа. Обычно это занимает несколько минут.', automaticPaymentSecurity: '',"
assert main.count(ru_old) == 1, f'RU payment copy anchor count={main.count(ru_old)}'
main = main.replace(ru_old, ru_new, 1)

kk_old = "automaticPayment: 'Құжат төлемі', automaticPaymentText: 'Құжатты Kaspi арқылы төлеңіз.', automaticPaymentSecurity: '',"
kk_new = "automaticPayment: 'Құжат төлемі', automaticPaymentText: 'Сәтті төлемнен кейін жүйе төлемді автоматты түрде растап, құжатты дайындауға кіріседі. Әдетте бұл бірнеше минутты алады.', automaticPaymentSecurity: '',"
assert main.count(kk_old) == 1, f'KK payment copy anchor count={main.count(kk_old)}'
main = main.replace(kk_old, kk_new, 1)

button_old = "{automaticPending && paymentUrl && <button className=\"primary wide\" onClick={() => window.open(paymentUrl, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button>}"
button_new = "{automaticPending && paymentUrl && <><button className=\"primary wide\" onClick={() => window.open(paymentUrl, '_blank', 'noopener,noreferrer')}><CreditCard size={18}/>{t.payKaspi}<ExternalLink size={15}/></button><p className=\"payment-guidance\">{t.automaticPaymentText}</p></>}"
assert main.count(button_old) == 1, f'automatic payment button anchor count={main.count(button_old)}'
main = main.replace(button_old, button_new, 1)
main_path.write_text(main, encoding='utf-8')

card_path = Path('miniapp/src/caseCard.js')
card = card_path.read_text(encoding='utf-8')
meta_old = """  const parts = [count > 0 ? `${t.materials}: ${count}` : t.noMaterials];
  if (item?.has_document) parts.push(`${t.document} · Word`);
  return parts.join(' · ');
"""
meta_new = """  const parts = [];
  if (count > 0) parts.push(`${t.materials}: ${count}`);
  if (item?.has_document) parts.push(`${t.document} · Word`);
  if (parts.length === 0) parts.push(t.noMaterials);
  return parts.join(' · ');
"""
assert card.count(meta_old) == 1, f'case-card meta anchor count={card.count(meta_old)}'
card_path.write_text(card.replace(meta_old, meta_new, 1), encoding='utf-8')

test_path = Path('miniapp/test/case-card.test.js')
test = test_path.read_text(encoding='utf-8')
ready_old = """  assert.doesNotMatch(meta, /Файлов: 0/);
  assert.match(meta, /Документ готов · Word/);
"""
ready_new = """  assert.doesNotMatch(meta, /Файлов: 0/);
  assert.doesNotMatch(meta, /Материалы не загружены/);
  assert.equal(meta, 'Документ готов · Word');
"""
assert test.count(ready_old) == 1, f'case-card ready test anchor count={test.count(ready_old)}'
test_path.write_text(test.replace(ready_old, ready_new, 1), encoding='utf-8')

styles_path = Path('miniapp/src/styles.css')
styles = styles_path.read_text(encoding='utf-8')
style_rule = '.payment-guidance{margin:12px auto 0;max-width:440px;color:#708098;font-size:13px;line-height:1.5;text-align:center}'
if style_rule not in styles:
    styles_path.write_text(styles.rstrip() + '\n' + style_rule + '\n', encoding='utf-8')

ux_test = Path('miniapp/test/payment-guidance.test.js')
ux_test.write_text("""import test from 'node:test';
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
  assert.match(source, /className=\"payment-guidance\"/);
  assert.match(source, /\{t\.automaticPaymentText\}/);
});

test('manual receipt payment path remains present and separate', () => {
  assert.match(source, /!automatic && !approved && !awaiting/);
  assert.match(source, /receipt-upload/);
  assert.match(source, /uploadDocReceipt/);
});
""", encoding='utf-8')
