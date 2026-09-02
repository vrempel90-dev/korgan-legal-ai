import test from 'node:test';
import assert from 'node:assert/strict';
import { createTelegramRuntime } from '../src/tmaRuntime.js';

function telegramMock() {
  const events = new Map();
  const calls = [];
  let backHandler = null;
  let mainHandler = null;

  const tg = {
    platform: 'android',
    colorScheme: 'dark',
    themeParams: { bg_color: '#111111', text_color: '#ffffff' },
    viewportHeight: 700,
    viewportStableHeight: 680,
    safeAreaInset: { top: 10, right: 0, bottom: 20, left: 0 },
    contentSafeAreaInset: { top: 4, right: 0, bottom: 8, left: 0 },
    ready: () => calls.push('ready'),
    expand: () => calls.push('expand'),
    setHeaderColor: value => calls.push(['header', value]),
    setBackgroundColor: value => calls.push(['background', value]),
    setBottomBarColor: value => calls.push(['bottom', value]),
    onEvent: (name, handler) => events.set(name, handler),
    offEvent: (name, handler) => { if (events.get(name) === handler) events.delete(name); },
    BackButton: {
      show: () => calls.push('back:show'),
      hide: () => calls.push('back:hide'),
      onClick: handler => { backHandler = handler; },
      offClick: handler => { if (backHandler === handler) backHandler = null; },
    },
    MainButton: {
      setText: text => calls.push(['main:text', text]),
      show: () => calls.push('main:show'),
      hide: () => calls.push('main:hide'),
      enable: () => calls.push('main:enable'),
      disable: () => calls.push('main:disable'),
      showProgress: () => calls.push('main:progress:on'),
      hideProgress: () => calls.push('main:progress:off'),
      onClick: handler => { mainHandler = handler; },
      offClick: handler => { if (mainHandler === handler) mainHandler = null; },
    },
  };

  return {
    tg,
    calls,
    events,
    clickBack: () => backHandler?.(),
    clickMain: () => mainHandler?.(),
  };
}

function documentMock() {
  const css = new Map();
  let backTarget = null;
  const root = {};
  return {
    css,
    setBackTarget: target => { backTarget = target; },
    doc: {
      documentElement: {
        style: { setProperty: (name, value) => css.set(name, value) },
        dataset: {},
      },
      querySelector: selector => selector === '#root' ? root : backTarget,
    },
  };
}

test('runtime initializes Telegram and binds theme/viewport CSS variables', () => {
  const telegram = telegramMock();
  const document = documentMock();
  const runtime = createTelegramRuntime({
    getWebApp: () => telegram.tg,
    doc: document.doc,
    win: null,
    MutationObserverClass: null,
  });

  assert.equal(runtime.init(), telegram.tg);
  assert.ok(telegram.calls.includes('ready'));
  assert.ok(telegram.calls.includes('expand'));
  assert.deepEqual(telegram.calls.find(item => Array.isArray(item) && item[0] === 'header'), ['header', '#090b0d']);
  assert.equal(document.css.get('--tg-theme-bg-color'), '#111111');
  assert.equal(document.css.get('--tg-theme-text-color'), '#ffffff');
  assert.equal(document.css.get('--tg-viewport-height'), '700px');
  assert.equal(document.css.get('--tg-viewport-stable-height'), '680px');
  assert.equal(document.css.get('--tg-safe-area-inset-top'), '10px');
  assert.equal(document.css.get('--tg-content-safe-area-inset-bottom'), '8px');
  assert.equal(document.doc.documentElement.dataset.tgColorScheme, 'dark');
});

test('native BackButton delegates to the currently rendered KORGAN back button', () => {
  const telegram = telegramMock();
  const document = documentMock();
  let clicks = 0;
  document.setBackTarget({ click: () => { clicks += 1; } });

  const runtime = createTelegramRuntime({
    getWebApp: () => telegram.tg,
    doc: document.doc,
    win: null,
    MutationObserverClass: null,
  });
  runtime.init();
  runtime.syncDomBackButton();
  telegram.clickBack();

  assert.equal(clicks, 1);
  assert.ok(telegram.calls.includes('back:show'));
});

test('MainButton lifecycle is declarative and dispose removes handlers', () => {
  const telegram = telegramMock();
  const document = documentMock();
  const runtime = createTelegramRuntime({
    getWebApp: () => telegram.tg,
    doc: document.doc,
    win: null,
    MutationObserverClass: null,
  });
  runtime.init();

  let clicks = 0;
  assert.equal(runtime.configureMainButton({ text: 'Продолжить', onClick: () => { clicks += 1; } }), true);
  telegram.clickMain();
  assert.equal(clicks, 1);
  assert.ok(telegram.calls.some(item => Array.isArray(item) && item[0] === 'main:text' && item[1] === 'Продолжить'));
  assert.ok(telegram.calls.includes('main:show'));

  runtime.dispose();
  telegram.clickMain();
  assert.equal(clicks, 1);
  assert.equal(telegram.events.size, 0);
});
