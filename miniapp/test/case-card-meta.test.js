/**
 * Подпись карточки дела описывает то, что в деле действительно есть.
 *
 * Подпись склеивала материалы и готовый документ в одну строку: «0 файл(ов) ·
 * DOCX». Человек читает её как «файлов ноль, а Word откуда-то есть», хотя это
 * два разных предмета — загруженные им материалы и подготовленный KORGAN
 * документ. Дело, описанное текстом без вложений, — обычный случай, и нулём
 * файлов оно не «пустое».
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { caseCardMeta } from '../src/caseTitle.js';

const ru = { materials: 'Материалы', documentReady: 'Документ готов' };

test('дело без материалов не сообщает о нулевых файлах', () => {
  assert.equal(caseCardMeta({ id: 'case-1', materials_count: 0 }, ru), 'case-1');
});

test('загруженные материалы называются числом', () => {
  assert.equal(caseCardMeta({ id: 'case-1', materials_count: 3 }, ru), 'case-1 · Материалы: 3');
});

test('готовый документ назван отдельно от материалов', () => {
  assert.equal(
    caseCardMeta({ id: 'case-1', materials_count: 2, has_document: true }, ru),
    'case-1 · Материалы: 2 · Документ готов',
  );
});

test('готовый документ виден и у дела без вложений', () => {
  assert.equal(
    caseCardMeta({ id: 'case-1', materials_count: 0, has_document: true }, ru),
    'case-1 · Документ готов',
  );
});
