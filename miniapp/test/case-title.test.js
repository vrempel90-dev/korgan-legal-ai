/**
 * Заголовок дела в списке — это название документа, а не его черновая строка.
 *
 * Заголовок карточки берётся из названия готового документа. Название пишет
 * юридический конвейер, и в нём законно остаются пометки о недостающих данных:
 * «ДОГОВОР ПОСТАВКИ № [ТРЕБУЕТ УТОЧНЕНИЯ: номер договора]». В самом документе
 * такая пометка нужна — она говорит юристу, что заполнить перед подачей, — но
 * в списке дел человек читает её как поломку приложения.
 *
 * Поэтому чистится только отображаемый заголовок. Название документа и его
 * содержание не меняются.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { caseDisplayTitle } from '../src/caseTitle.js';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

test('пометка о недостающем реквизите не доходит до списка дел', () => {
  const title = caseDisplayTitle(
    { title: 'ДОГОВОР ПОСТАВКИ № [ТРЕБУЕТ УТОЧНЕНИЯ: номер договора]' },
    'Договор',
  );

  assert.equal(title, 'ДОГОВОР ПОСТАВКИ');
});

test('технический заполнитель не доходит до списка дел', () => {
  assert.equal(caseDisplayTitle({ title: 'ДОГОВОР ПОСТАВКИ № <UNKNOWN>' }, 'Договор'), 'ДОГОВОР ПОСТАВКИ');
  assert.equal(caseDisplayTitle({ title: 'Договор № UNKNOWN' }, 'Договор'), 'Договор');
});

test('казахская пометка обрабатывается так же', () => {
  const title = caseDisplayTitle({ title: 'ЖЕТКІЗУ ШАРТЫ № [НАҚТЫЛАУ ҚАЖЕТ: шарт нөмірі]' }, 'Шарт');

  assert.equal(title, 'ЖЕТКІЗУ ШАРТЫ');
});

test('заголовок без пометок остаётся нетронутым', () => {
  const title = 'Исковое заявление о взыскании уплаченной по договору суммы';

  assert.equal(caseDisplayTitle({ title }, 'Исковое заявление'), title);
});

test('пустой после очистки заголовок уступает место типу документа', () => {
  assert.equal(caseDisplayTitle({ title: '[ТРЕБУЕТ УТОЧНЕНИЯ: наименование документа]' }, 'Договор'), 'Договор');
  assert.equal(caseDisplayTitle({ title: '   ' }, 'Договор'), 'Договор');
  assert.equal(caseDisplayTitle({}, 'Договор'), 'Договор');
  assert.equal(caseDisplayTitle(null, 'Договор'), 'Договор');
});

test('заголовок не обрывается посреди слова и не теряет хвост', () => {
  const title = caseDisplayTitle(
    { title: 'Претензия к ТОО «Мебель Стандарт» [ТРЕБУЕТ УТОЧНЕНИЯ: БИН] о возврате оплаты' },
    'Претензия',
  );

  assert.equal(title, 'Претензия к ТОО «Мебель Стандарт» о возврате оплаты');
});

test('карточка использует очищенный заголовок', () => {
  const start = app.indexOf('className="case-list-item"');
  const list = app.slice(start, start + 400);

  assert.match(list, /caseDisplayTitle\(/, 'список дел печатает сырое название документа');
  assert.doesNotMatch(list, /\{item\.title \|\| title\}/, 'список дел печатает сырое название документа');
});
