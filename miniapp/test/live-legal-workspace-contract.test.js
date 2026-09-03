import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { safeHttpsUrl } from '../src/safeExternalUrl.js';

const here = dirname(fileURLToPath(import.meta.url));
const miniapp = join(here, '..');
const src = join(miniapp, 'src');

const index = readFileSync(join(miniapp, 'index.html'), 'utf8');
const ui = readFileSync(join(src, 'legalWorkspaceUi.js'), 'utf8');
const css = readFileSync(join(src, 'legal-workspace.css'), 'utf8');

test('live MiniApp подключает Legal Workspace поверх существующего UI', () => {
  assert.match(index, /\/src\/approved-compat\.css/);
  assert.match(index, /\/src\/legal-workspace\.css/);
  assert.match(index, /\/src\/main\.jsx/);
  assert.match(index, /\/src\/legalWorkspaceUi\.js/);
  assert.ok(index.indexOf('/src/legal-workspace.css') > index.indexOf('/src/approved-compat.css'));
  assert.ok(index.indexOf('/src/legalWorkspaceUi.js') > index.indexOf('/src/main.jsx'));
});

test('live Legal Workspace использует только legal-workspace API и не включает оплату', () => {
  assert.match(ui, /\/miniapp\/legal-workspace\/state-duty/);
  assert.match(ui, /\/miniapp\/legal-workspace\/late-penalty-353/);
  assert.match(ui, /\/miniapp\/legal-workspace\/stress-test/);
  assert.doesNotMatch(ui, /PAYMENTS_ENABLED/);
  assert.doesNotMatch(ui, /\/payments\//);
});

test('Legal Workspace использует общий transport с bounded timeout и AbortSignal', () => {
  assert.match(ui, /createApiTransport/);
  assert.match(ui, /timeoutMs:\s*30000/);
  assert.match(ui, /timeoutMs:\s*110000/);
  assert.match(ui, /signal:\s*scoped\.signal/);
  assert.doesNotMatch(ui, /await\s+fetch\s*\(/);
});

test('Stress Test и весь sheet поддерживают сохранённый язык приложения', () => {
  assert.match(ui, /korgan-miniapp-state-v1/);
  assert.match(ui, /const COPY\s*=\s*\{/);
  assert.match(ui, /launcher:\s*'⚖ Заң құралдары'/);
  assert.match(ui, /language\s*\}\),/);
  assert.doesNotMatch(ui, /document\.documentElement\.lang/);
});

test('launcher появляется только после consent и скрывается на chat screen', () => {
  assert.match(ui, /app-shell:not\(\.consent-shell\)/);
  assert.match(ui, /chat-shell/);
  assert.match(ui, /button\.hidden\s*=\s*chatOpen/);
});

test('список дел защищён от позднего ответа старого запроса', () => {
  assert.match(ui, /caseLoadSequence/);
  assert.match(ui, /requestId\s*!==\s*caseLoadSequence/);
  assert.match(ui, /select\.replaceChildren/);
});

test('remount инвалидирует и отменяет запросы старой панели', () => {
  assert.match(ui, /let mountEpoch\s*=\s*0/);
  assert.match(ui, /beginScopedRequest/);
  assert.match(ui, /epoch === mountEpoch/);
  assert.match(ui, /requestId === actionSequence\[kind\]/);
  assert.match(ui, /abortActiveRequests\(\)/);
  assert.match(ui, /controller\.abort\(/);
  assert.match(ui, /if \(!scoped\.isCurrent\(\)\) return/);
});

test('ответы юридических инструментов вставляются как текст, а не как HTML', () => {
  assert.match(ui, /box\.textContent\s*=\s*text/);
  assert.doesNotMatch(ui, /box\.innerHTML\s*=\s*text/);
});

test('внешние ссылки разрешают только абсолютный HTTPS и runtime импортирует тот же sanitizer', () => {
  assert.match(ui, /import \{ safeHttpsUrl \} from '.\/safeExternalUrl\.js'/);
  assert.equal(safeHttpsUrl('https://adilet.zan.kz/rus/docs/K940001000_'), 'https://adilet.zan.kz/rus/docs/K940001000_');
  assert.equal(safeHttpsUrl('javascript:alert(1)'), '');
  assert.equal(safeHttpsUrl('data:text/html,boom'), '');
  assert.equal(safeHttpsUrl('http://example.com'), '');
  assert.equal(safeHttpsUrl('/relative/path'), '');
});

test('панель Legal Workspace не скрывает и не заменяет существующий интерфейс', () => {
  assert.match(css, /korgan-legal-tools-button/);
  assert.match(css, /korgan-legal-tools-backdrop/);
  assert.doesNotMatch(css, /#root\s*\{[^}]*display\s*:\s*none/);
});
