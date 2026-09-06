/**
 * Карточка дела показывает имя дела и то, что в нём есть.
 *
 * В список дел попадали «ДОГОВОР ПОСТАВКИ № <UNKNOWN>» и
 * «№ [ТРЕБУЕТ УТОЧНЕНИЯ: номер договора]»: первое — незаполненная подстановка,
 * второе — внутренняя пометка конвейера, адресованная юристу внутри документа.
 * Подпись при этом читалась как «Файлов: 0 · Word» — ноль файлов и всё же
 * формат Word.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { caseCardMeta, caseCardTitle, documentTypeName, isDisplayableTitle } from '../src/caseCard.js';

test('незаполненная подстановка никогда не становится именем дела', () => {
  const item = { title: 'ДОГОВОР ПОСТАВКИ № <UNKNOWN>', document_type: 'contract' };
  const title = caseCardTitle(item, 'ru');

  assert.doesNotMatch(title, /unknown/i);
  assert.equal(title, 'Договор');
});

test('внутренняя пометка конвейера не показывается как имя дела', () => {
  const item = { title: '№ [ТРЕБУЕТ УТОЧНЕНИЯ: номер договора]', document_type: 'contract' };
  const title = caseCardTitle(item, 'ru');

  assert.doesNotMatch(title, /ТРЕБУЕТ УТОЧНЕНИЯ/);
  assert.doesNotMatch(title, /\[/);
  assert.equal(title, 'Договор');
});

test('обрубок «ДОГОВОР ПОСТАВКИ №» без номера тоже не проходит', () => {
  assert.equal(isDisplayableTitle('ДОГОВОР ПОСТАВКИ №'), false);
  assert.equal(caseCardTitle({ title: 'ДОГОВОР ПОСТАВКИ №', document_type: 'contract' }), 'Договор');
});

test('нормальное название документа остаётся как есть', () => {
  const item = { title: 'ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности', document_type: 'claim' };
  assert.equal(caseCardTitle(item, 'ru'), 'ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности');
});

test('дело без названия называется по типу документа на языке клиента', () => {
  assert.equal(caseCardTitle({ document_type: 'pretrial' }, 'ru'), 'Досудебная претензия');
  assert.equal(caseCardTitle({ document_type: 'pretrial' }, 'kk'), 'Сотқа дейінгі талап');
  assert.equal(documentTypeName('pretrial_response', 'ru'), 'Ответ на претензию');
});

test('нулевые материалы не соседствуют с форматом готового файла', () => {
  const meta = caseCardMeta({ materials_count: 0, has_document: false }, 'ru');

  assert.doesNotMatch(meta, /Word/);
  assert.equal(meta, 'Материалы не загружены');
});

test('готовый документ назван отдельно от материалов дела', () => {
  const meta = caseCardMeta({ materials_count: 3, has_document: true }, 'ru');

  assert.match(meta, /Материалов: 3/);
  assert.match(meta, /Документ готов · Word/);
});

test('готовый документ без материалов не превращается в «Файлов: 0 · Word»', () => {
  const meta = caseCardMeta({ materials_count: 0, has_document: true }, 'ru');

  assert.doesNotMatch(meta, /Файлов: 0/);
  assert.doesNotMatch(meta, /Материалы не загружены/);
  assert.equal(meta, 'Документ готов · Word');
});

test('подпись переведена на казахский полностью', () => {
  const meta = caseCardMeta({ materials_count: 2, has_document: true }, 'kk');
  assert.match(meta, /Материал: 2/);
  assert.match(meta, /Құжат дайын/);
});
