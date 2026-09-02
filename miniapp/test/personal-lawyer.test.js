/**
 * Плитка проверки живым юристом принадлежит React-приложению и соответствует
 * утверждённой главной странице KORGAN. Язык берётся из состояния приложения,
 * без DOM-патчей и второго источника истины.
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

test('текст плитки проверки выбирается по языку приложения', () => {
  assert.equal(personalLawyerCopy('ru').title, 'Проверка юристом');
  assert.equal(personalLawyerCopy('kk').title, 'Заңгер тексеруі');
});

test('у плитки есть доступное имя на обоих языках', () => {
  assert.match(personalLawyerCopy('ru').aria, /WhatsApp/);
  assert.match(personalLawyerCopy('kk').aria, /WhatsApp/);
});

test('неизвестный язык не оставляет плитку без текста', () => {
  assert.deepEqual(personalLawyerCopy('en'), personalLawyerCopy('ru'));
  assert.deepEqual(personalLawyerCopy(undefined), personalLawyerCopy('ru'));
});

test('проверка юристом ведёт на существующий WhatsApp-контакт', () => {
  assert.equal(PERSONAL_LAWYER_URL, 'https://wa.me/77005000553');
});

test('ни один модуль не следит за изменениями всего документа', () => {
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

test('страница не подключает DOM-патч и грузит утверждённый presentation-layer', () => {
  const html = readFileSync(join(miniapp, 'index.html'), 'utf8');
  assert.ok(!html.includes('personal-lawyer.js'), 'index.html всё ещё грузит DOM-патч карточки');
  assert.ok(html.includes('/src/approved-compat.css'), 'утверждённый светлый presentation-layer не подключён');
  assert.ok(!html.includes('/src/personal-lawyer.css'), 'старый graphite-стиль карточки снова подключён');
});
