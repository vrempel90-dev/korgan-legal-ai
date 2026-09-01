/**
 * Карточка персонального юриста принадлежит приложению, а не патчу поверх него.
 *
 * Карточка внедрялась отдельным модулем в контейнер, которым владеет React, а
 * язык определялся вычитыванием отрисованного текста страницы. Из-за этого у
 * одного узла было два владельца, а у языка — два источника истины.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PERSONAL_LAWYER_URL, personalLawyerCopy } from '../src/personalLawyer.js';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const src = join(miniapp, 'src');

test('текст карточки выбирается по языку приложения, а не по тексту страницы', () => {
  assert.equal(personalLawyerCopy('ru').title, 'Ваш персональный юрист');
  assert.equal(personalLawyerCopy('kk').title, 'Сіздің жеке заңгеріңіз');
});

test('у карточки есть доступное имя на обоих языках', () => {
  assert.match(personalLawyerCopy('ru').aria, /WhatsApp/);
  assert.match(personalLawyerCopy('kk').aria, /WhatsApp/);
});

test('неизвестный язык не оставляет карточку без текста', () => {
  // Язык приходит из сохранённого состояния и может оказаться любым.
  assert.deepEqual(personalLawyerCopy('en'), personalLawyerCopy('ru'));
  assert.deepEqual(personalLawyerCopy(undefined), personalLawyerCopy('ru'));
});

test('карточка ведёт на WhatsApp персонального юриста', () => {
  assert.equal(PERSONAL_LAWYER_URL, 'https://wa.me/77005000553');
});

test('ни один модуль не следит за изменениями всего документа', () => {
  /*
   * Наблюдатель за всем документом вызывал перерисовку карточки, а перерисовка
   * меняла DOM и снова будила наблюдателя. Цикл ограничивался только кадром
   * анимации, поэтому карточка переписывалась каждый кадр всё время работы
   * приложения, и каждый раз выполнялось чтение innerText — принудительный
   * пересчёт вёрстки на телефоне.
   */
  // Комментарий, объясняющий снятый приём, — не сам приём: сравнивается код.
  const withoutComments = (code) =>
    code.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');

  const offenders = [];
  for (const name of readdirSync(src)) {
    if (!name.endsWith('.js') && !name.endsWith('.jsx')) continue;
    const code = withoutComments(readFileSync(join(src, name), 'utf8'));
    if (/new\s+MutationObserver/.test(code)) offenders.push(name);
    if (/document\.body[?.]*\.innerText/.test(code)) offenders.push(name);
  }
  assert.deepEqual(offenders, []);
});

test('страница не подключает патч, дописывающий DOM поверх React', () => {
  const html = readFileSync(join(miniapp, 'index.html'), 'utf8');
  assert.ok(!html.includes('personal-lawyer.js'), 'index.html всё ещё грузит патч карточки');
  // Стиль карточки остаётся: меняется владелец разметки, а не оформление.
  assert.ok(html.includes('personal-lawyer.css'), 'оформление карточки пропало');
});
