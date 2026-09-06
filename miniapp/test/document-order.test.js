/**
 * «Договор» стоит последним в списке типов документов.
 *
 * Порядок задаётся самим массивом документов, а не оформлением: список
 * отрисовывается перебором в объявленном порядке, поэтому CSS-перестановка
 * рассинхронизировала бы то, что видит человек, с тем, что отправляет клиент.
 * Договор — единственный тип, который не является судебным документом, и в
 * перечне он замыкает список, а не разрывает судебные документы посередине.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

const block = app.slice(app.indexOf('const DOCUMENTS = ['), app.indexOf('const L = {'));
const ids = [...block.matchAll(/\{\s*id:\s*'([a-z_]+)'/g)].map((match) => match[1]);

test('договор объявлен последним типом документа', () => {
  assert.ok(ids.length >= 5, `в списке документов найдено ${ids.length} типов`);
  assert.equal(ids.at(-1), 'contract', `порядок типов: ${ids.join(', ')}`);
});

test('остальные типы документов сохранены', () => {
  for (const id of ['claim', 'response', 'pretrial', 'pretrial_response']) {
    assert.ok(ids.includes(id), `тип документа ${id} исчез из списка`);
  }
});

test('каждый тип документа сохраняет русскую и казахскую подписи', () => {
  const entries = block.split(/\{\s*id:/).slice(1);
  assert.equal(entries.length, ids.length);
  for (const entry of entries) {
    assert.match(entry, /ru:\s*\[[^\]]+\]/, 'потеряна русская подпись типа документа');
    assert.match(entry, /kk:\s*\[[^\]]+\]/, 'потеряна казахская подпись типа документа');
  }
});
