/**
 * В плашку попадает объяснение, а не служебный ответ сервера.
 *
 * Текст ошибки брался из ответа как есть: `error.message || t.down`. Серверные
 * `detail` в норме служебные и англоязычные, поэтому пользователь читал на
 * своём экране «Case not found», «Document not generated», а при рассинхроне
 * parity — «KORGAN professional legal runtime is not ready» во весь экран на
 * старте. Худший из них — «KORGAN generator unavailable: <имя>»: он выносит
 * клиенту внутреннее имя генератора. Туда же уходил и код транспорта
 * `KORGAN_API_NOT_CONNECTED`, у которого текста для человека нет вовсе.
 *
 * Полезные серверные сообщения при этом существуют и написаны на языке
 * клиента: «Документ по этому делу ещё не готов», «Kaspi ОФД временно
 * недоступен…». Терять их нельзя, поэтому граница проходит по языку: написанное
 * человеку показывается, служебная латиница заменяется своей формулировкой.
 */

import test from 'node:test';
import { clientDocumentNotes } from '../src/clientMessage.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { clientMessage } from '../src/clientMessage.js';

const here = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(join(here, '..', 'src', 'main.jsx'), 'utf8');

const TEXTS = {
  sessionExpired: 'Сессия Telegram истекла.',
  notFound: 'Данные не найдены.',
  down: 'Сервис временно недоступен',
};

const failure = (message, properties = {}) => Object.assign(new Error(message), properties);

test('служебный ответ сервера не показывается клиенту', () => {
  const shown = clientMessage(
    failure('Case not found', { code: 'KORGAN_API_HTTP_ERROR', status: 404 }),
    TEXTS,
  );

  assert.equal(shown, TEXTS.notFound);
});

test('внутреннее имя генератора не выносится клиенту', () => {
  const shown = clientMessage(
    failure('KORGAN generator unavailable: ClaimPipelineV2Adapter', {
      code: 'KORGAN_API_HTTP_ERROR',
      status: 503,
    }),
    TEXTS,
  );

  assert.equal(shown, TEXTS.down);
  assert.doesNotMatch(shown, /ClaimPipelineV2Adapter/);
});

test('несовпадение parity не объясняется клиенту по-английски', () => {
  const shown = clientMessage(failure('KORGAN professional legal runtime is not ready'), TEXTS);

  assert.equal(shown, TEXTS.down);
});

test('код транспорта без текста для человека не показывается', () => {
  const shown = clientMessage(
    failure('KORGAN_API_NOT_CONNECTED', { code: 'KORGAN_API_NOT_CONNECTED' }),
    TEXTS,
  );

  assert.equal(shown, TEXTS.down);
});

test('серверное сообщение на языке клиента сохраняется', () => {
  const shown = clientMessage(
    failure('Документ по этому делу ещё не готов', { code: 'KORGAN_API_HTTP_ERROR', status: 404 }),
    TEXTS,
  );

  assert.equal(shown, 'Документ по этому делу ещё не готов');
});

test('казахское серверное сообщение сохраняется', () => {
  const shown = clientMessage(failure('Құжат әзірге дайын емес'), TEXTS);

  assert.equal(shown, 'Құжат әзірге дайын емес');
});

test('технические названия в сообщениях транспорта скрываются', () => {
  const timeout = clientMessage(
    failure('Превышено время ожидания ответа KORGAN API', { code: 'KORGAN_API_TIMEOUT' }),
    TEXTS,
  );
  const network = clientMessage(
    failure('Не удалось подключиться к KORGAN API', { code: 'KORGAN_API_NETWORK_ERROR' }),
    TEXTS,
  );

  assert.equal(timeout, TEXTS.down);
  assert.equal(network, TEXTS.down);
});

test('отказ в подписи Telegram объясняется отдельно', () => {
  const shown = clientMessage(
    failure('Подпись Telegram недействительна', { code: 'KORGAN_API_UNAUTHORIZED', status: 403 }),
    TEXTS,
  );

  assert.equal(shown, TEXTS.sessionExpired);
});

test('ошибка без текста не оставляет плашку пустой', () => {
  assert.equal(clientMessage(failure(''), TEXTS), TEXTS.down);
  assert.equal(clientMessage(undefined, TEXTS), TEXTS.down);
});

test('приложение показывает ошибки через это правило', () => {
  assert.match(app, /from '\.\/clientMessage'/, 'правило показа ошибок снова своё в main.jsx');
  assert.match(
    app,
    /const clientMessage = error => messageForClient\(error, t\)/,
    'ошибки показываются в обход общего правила',
  );
});

test('замена служебному тексту есть на обоих языках', () => {
  const declarations = app.match(/^\s*notFound: '.+',$/gm) || [];

  assert.equal(declarations.length, 2, 'подстановка для «не найдено» есть не на всех языках');
  for (const declaration of declarations) {
    assert.match(declaration, /[Ѐ-ӿ]/, 'замена служебному тексту сама написана служебно');
  }
});

test('служебная пометка на русском не попадает в сообщение или документ', () => {
  const notes = ['Проверьте адрес ответчика', 'Сбой Tole webhook: provider_status', 'SENIOR_PREFLIGHT: проверить факты'];
  assert.deepEqual(clientDocumentNotes(notes), ['Проверьте адрес ответчика']);
  assert.equal(clientMessage(failure(notes[1]), TEXTS), TEXTS.down);
  assert.deepEqual(clientDocumentNotes(null), []);
});
