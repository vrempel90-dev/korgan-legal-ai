import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { documentConsultationLabel } from '../src/documentConsultationUi.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

test('CTA называет конкретный сгенерированный документ', () => {
  assert.equal(
    documentConsultationLabel('Исковое заявление о взыскании долга', 'ru'),
    'Консультация по документу: Исковое заявление о взыскании долга',
  );
  assert.equal(
    documentConsultationLabel('Талап қою арызы', 'kk'),
    'Осы құжат бойынша кеңес: Талап қою арызы',
  );
});

test('клиент перед консультацией получает SHA-256 текущего DOCX', () => {
  const api = readFileSync(join(src, 'korganApi.js'), 'utf8');
  assert.match(api, /\/miniapp\/cases\/\$\{encodeURIComponent\(id\)\}/);
  assert.match(api, /document_revision:\s*documentRevision\s*\|\|\s*null/);
  assert.match(api, /result\?\.case\?\.document_revision/);
});

test('видимый UI загружает document-specific консультацию', () => {
  const html = readFileSync(join(here, '..', 'index.html'), 'utf8');
  const ui = readFileSync(join(src, 'documentConsultationUi.js'), 'utf8');
  assert.match(html, /documentConsultationUi\.js/);
  assert.match(ui, /Консультация по документу:/);
  assert.match(ui, /data-document-consultation/);
  assert.match(ui, /Скачать готовый DOCX/);
});

test('клиентский интерфейс не рекламирует Telegram-агента как часть продукта', () => {
  const copy = readFileSync(join(src, 'brandCopy.js'), 'utf8');
  assert.match(copy, /отдельном защищённом production‑контуре KORGAN/);
  assert.match(copy, /обязательные финальные проверки качества/);
});
