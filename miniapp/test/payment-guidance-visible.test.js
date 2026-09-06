/**
 * Подсказка о том, что будет после оплаты, видна под кнопкой Kaspi на любом пути.
 *
 * Экран оплаты рисует кнопку «Оплатить через Kaspi» из двух разных веток —
 * автоматическое подтверждение провайдером и подтверждение по загруженному
 * чеку. Пояснение добавили только в первую, поэтому на втором пути человек
 * видел сумму и кнопку без единого слова о том, что произойдёт дальше: экран
 * выглядел так, будто после возврата из банка нужно нажать что-то ещё.
 *
 * Проверяется не наличие строки в словаре, а то, что она стоит сразу за каждой
 * кнопкой оплаты в разметке этого экрана.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

/** Разметка экрана «Оплата документа» целиком. */
const screen = (() => {
  const start = source.indexOf("if (view === 'doc-payment')");
  assert.ok(start > 0, 'экран оплаты документа не найден');
  const end = source.indexOf("if (view === 'generating')", start);
  return source.slice(start, end > start ? end : start + 6000);
})();

/** Каждая кнопка оплаты на этом экране и хвост разметки сразу за ней. */
function paymentButtons() {
  const marker = '{t.payKaspi}';
  const found = [];
  let from = 0;
  for (;;) {
    const at = screen.indexOf(marker, from);
    if (at < 0) return found;
    found.push(screen.slice(at, at + 320));
    from = at + marker.length;
  }
}

test('на экране оплаты есть кнопки Kaspi', () => {
  assert.ok(paymentButtons().length >= 2, 'ожидались оба пути подтверждения оплаты');
});

test('под каждой кнопкой оплаты стоит пояснение о подготовке документа', () => {
  for (const [index, tail] of paymentButtons().entries()) {
    assert.match(
      tail,
      /className="payment-guidance"[^>]*>\{t\.automaticPaymentText\}/,
      `под кнопкой оплаты №${index + 1} нет пояснения о том, что будет после оплаты`,
    );
  }
});

test('пояснение стоит именно под кнопкой, а не после загрузки чека', () => {
  const [, manual] = paymentButtons();
  const guidance = manual.indexOf('payment-guidance');
  const receipt = manual.indexOf('receipt-upload');

  assert.ok(guidance > 0, 'на пути с чеком пояснение отсутствует');
  assert.ok(receipt < 0 || guidance < receipt, 'пояснение оказалось ниже загрузки чека');
});

test('текст пояснения существует на обоих языках', () => {
  assert.match(
    source,
    /После успешной оплаты система автоматически подтвердит платёж и приступит к подготовке документа\. Обычно это занимает несколько минут\./,
  );
  assert.match(
    source,
    /Сәтті төлемнен кейін жүйе төлемді автоматты түрде растап, құжатты дайындауға кіріседі\. Әдетте бұл бірнеше минутты алады\./,
  );
});
