/**
 * Состояние дела берётся из данных, а не вычитывается из текста на экране.
 *
 * Боевой дефект: идентификатор дела парсился из подписи карточки — «всё до
 * первого « · »». Пока подпись начиналась с номера дела, это работало. После
 * смены подписи на «Файлов: 0 · Word» тем же способом стало извлекаться
 * «Файлов: 0», и приложение опрашивало несуществующее дело:
 *
 *     GET /miniapp/cases/%D0%A4%D0%B0%D0%B9%D0%BB%D0%BE%D0%B2%3A%200/generation → 404
 *
 * Ошибка опроса при этом планировала следующий опрос — по несколько запросов в
 * секунду с каждого открытого экрана «Мои дела», бесконечно. Карточки
 * показывали «Статус временно недоступен», а полоска подготовки висела и на
 * завершённых делах.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { caseProgressSnapshot } from '../src/caseProgressState.js';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const ui = readFileSync(join(src, 'uiPreferences.js'), 'utf8');
const app = readFileSync(join(src, 'main.jsx'), 'utf8');

test('идентификатор дела приходит атрибутом данных, а не из подписи', () => {
  assert.match(ui, /button\?\.dataset\?\.caseId/, 'идентификатор дела больше не берётся из данных');
  assert.doesNotMatch(
    ui,
    /caseIdFromButton[\s\S]{0,400}querySelector\('small'\)/,
    'идентификатор дела всё ещё вычитывается из текста карточки',
  );
});

test('карточка отдаёт свой идентификатор и признак готовности', () => {
  assert.match(app, /data-case-id=\{item\.id\}/, 'карточка не публикует идентификатор дела');
  assert.match(app, /data-case-status=/, 'карточка не публикует признак готовности');
});

test('подпись карточки больше не притворяется идентификатором', () => {
  // Подпись собирает отдельный модуль, и её текст ни на что не влияет.
  assert.match(app, /caseCardMeta\(item, language\)/);
  assert.doesNotMatch(app, /<small>\{t\.files\}: /, 'подпись снова совпала со старым форматом');
});

test('опрос завершённого дела не начинается вовсе', () => {
  assert.match(
    ui,
    /button\.dataset\.caseStatus === 'completed'/,
    'готовое дело по-прежнему опрашивается',
  );
});

test('число неудачных опросов ограничено сверху', () => {
  assert.match(ui, /MAX_PROBE_FAILURES\s*=\s*[1-9]/, 'предел неудачных опросов не задан');
  assert.doesNotMatch(
    ui,
    /catch\s*\{[\s\S]{0,200}shouldContinue = true;/,
    'ошибка опроса снова продлевает опрос без предела',
  );
});

test('диагностика остаётся в консоли, а не уходит на экран', () => {
  assert.match(ui, /console\.warn\(`KORGAN case progress probe failed/);
  assert.doesNotMatch(ui, /catch\s*\{\s*\}/, 'ошибка проглатывается пустым catch');
});

test('терминальные состояния объявлены и не опрашиваются', async () => {
  const { TERMINAL_KINDS } = await import('../src/caseProgressState.js');
  assert.ok(TERMINAL_KINDS.has('ready'));
  assert.ok(TERMINAL_KINDS.has('failed'));

  const ready = caseProgressSnapshot({
    job: { job_id: 'j', case_id: 'c', status: 'succeeded', stage: 'completed', progress: 100, document_ready: true, retryable: false },
    document: { filename: 'claim.docx' },
  });
  assert.equal(ready.poll, false);
  assert.equal(ready.terminal, true);

  const failed = caseProgressSnapshot({
    job: { job_id: 'j', case_id: 'c', status: 'failed', stage: 'failed', progress: 0, document_ready: false, retryable: true, error: 'нет' },
  });
  assert.equal(failed.poll, false);
  assert.equal(failed.terminal, true);
});

test('идущая подготовка по-прежнему опрашивается и показывает свой процент', () => {
  const running = caseProgressSnapshot({
    job: { job_id: 'j', case_id: 'c', status: 'running', stage: 'legal_research', progress: 20, document_ready: false, retryable: false },
  });
  assert.equal(running.kind, 'running');
  assert.equal(running.progress, 20);
  assert.equal(running.poll, true);
  assert.equal(running.terminal, false);
});

test('полоска подготовки положена только незавершённым состояниям', () => {
  assert.match(ui, /PROGRESS_KINDS = new Set\(\['running', 'unavailable'\]\)/);
  assert.match(
    ui,
    /if \(!snapshot\.poll && !PROGRESS_KINDS\.has\(snapshot\.kind\)\)/,
    'полоска снова рисуется для любого состояния',
  );
});

test('«Договор» — последний пункт в разделе документов', () => {
  const block = app.slice(app.indexOf('const DOCUMENTS = ['), app.indexOf('];', app.indexOf('const DOCUMENTS = [')));
  const ids = [...block.matchAll(/\{ id: '([a-z_]+)'/g)].map(match => match[1]);

  assert.ok(ids.length >= 5, 'список документов не разобран');
  assert.equal(ids[ids.length - 1], 'contract', '«Договор» должен быть последним');
  for (const id of ['claim', 'response', 'pretrial', 'pretrial_response']) {
    assert.ok(ids.includes(id), `категория ${id} пропала из списка`);
  }
});
