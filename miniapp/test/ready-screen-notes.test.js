/**
 * Экран выпуска говорит с клиентом его словами, а не протоколом проверок.
 *
 * Замечания выводились прямо из `verification_notes` и `quality_issues` —
 * списков, которые внутренние гейты ведут для самих себя. Оплативший документ
 * человек читал на экране строку вида «FILING_ACTION: указать банковские
 * реквизиты истца · Обязательство должно исполняться надлежащим образом
 * [основание: статья 272 ГК РК; текст нормы: …; источник: https://…]»: чужой
 * служебный префикс, разметка привязки к источнику и ссылка.
 *
 * Сервер составляет перечень, написанный для клиента, — `todo_before_filing`.
 * Туда же сервер добавляет только безопасные для клиента нерешённые расчётные
 * пункты и рекомендацию обратиться к юристу KORGAN. Экран не пытается сам
 * интерпретировать внутренние verification notes.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');
const ready = app.slice(app.indexOf("if (view === 'ready')"), app.indexOf("if (view === 'cases')"));

test('экран выпуска показывает серверный перечень перед подачей', () => {
  assert.match(ready, /todo_before_filing/, 'перечень задач перед подачей на экран не выводится');
});

test('протокол проверок не доходит до экрана выпуска', () => {
  assert.doesNotMatch(ready, /verification_notes/, 'клиент читает замечания гейтов как есть');
  assert.doesNotMatch(ready, /quality_issues/, 'клиент читает замечания гейтов как есть');
});

test('состояние выпуска показывается словом, а не служебным значением', () => {
  assert.doesNotMatch(ready, /release_status/, 'на экран выводится внутреннее значение release_status');
});

test('рядом с нерешёнными пунктами остаётся прямой переход к живому юристу', () => {
  assert.match(ready, /WHATSAPP_URL/, 'экран готового документа не ведёт к юристу KORGAN');
  assert.match(ready, /liveReview/, 'кнопка проверки живым юристом исчезла с экрана');
});
