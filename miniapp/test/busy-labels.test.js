/**
 * Надпись на кнопке рассказывает о своём действии, а не о любой занятости.
 *
 * Занятость в приложении одна на всех: пока идёт любой запрос, остальные
 * кнопки гаснут, и это правильно — действия выполняются по одному. Но подписи
 * читали ту же общую занятость и объявляли чужую работу своей. Нажатие
 * «Скачать готовый DOCX» превращало соседнюю кнопку в «Проверяю право и
 * формирую Word…», хотя ничего не формировалось; «Проверить оплату» делало то
 * же самое на экране оплаты, а удаление дела подписывало загрузку материалов
 * словами «Обрабатываю материалы…».
 *
 * Пользователь читает это как отчёт о происходящем — и получает ложный.
 * Поэтому занятость называет себя: кнопка показывает свою работу, только если
 * занята именно ею. Гаснут при этом по-прежнему все.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

const lineWith = fragment => app.split('\n').find(line => line.includes(fragment));

/** Тело обработчика: объявление и всё до закрывающей его строки. */
const bodyOf = declaration => {
  const start = app.indexOf(declaration);
  if (start < 0) return '';
  const end = app.indexOf('\n  };', start);
  return app.slice(start, end < 0 ? start : end);
};

test('занятость называет себя, оставаясь одной на всё приложение', () => {
  assert.match(app, /const \[busyAction, setBusyAction\] = useState\(''\)/, 'занятость не различает действий');
  assert.match(app, /const busy = Boolean\(busyAction\)/, 'общая блокировка кнопок потеряна');
});

test('подготовка документа объявляется только подготовкой', () => {
  const handler = bodyOf('const generateDocument =');
  assert.ok(handler, 'запуск подготовки не найден');
  assert.match(handler, /setBusy\('generate'\)/, 'подготовка не отличает себя от прочей занятости');

  for (const fragment of ['onClick={generateDocument}']) {
    const button = app.split('\n').filter(line => line.includes(fragment));
    assert.ok(button.length >= 1, 'кнопка подготовки не найдена');
    for (const line of button) {
      assert.doesNotMatch(
        line,
        /busy \? (<LoaderCircle[^>]*\/>|t\.generating)/,
        'кнопка называет подготовкой любое чужое действие',
      );
      assert.match(line, /busyAction === 'generate'/, 'кнопка не проверяет, что занята именно подготовкой');
    }
  }
});

test('загрузка материалов подписывается своим действием', () => {
  const handler = bodyOf('const uploadMaterial =');
  assert.ok(handler, 'загрузка материалов не найдена');
  assert.match(handler, /setBusy\('upload'\)/, 'загрузка не отличает себя от прочей занятости');

  const label = lineWith('onChange={uploadMaterial}');
  assert.ok(label, 'поле загрузки материалов не найдено');
  assert.match(label, /busyAction === 'upload' \? t\.processing/, 'надпись объявляет обработкой чужую работу');
});

test('кнопки по-прежнему гаснут на время любого действия', () => {
  const label = lineWith('onChange={uploadMaterial}');
  assert.match(label, /disabled=\{busy\}/, 'во время чужого действия можно начать загрузку материалов');
  const download = lineWith('onClick={deliverActiveDocument}');
  assert.match(download, /disabled=\{busy\}/, 'во время чужого действия можно начать скачивание');
});
