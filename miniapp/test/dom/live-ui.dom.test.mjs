/**
 * Проверка того, что человек действительно видит на экране.
 *
 * Статическая проверка исходника однажды уже дала ложное «исправлено»: строка
 * стояла в JSX, попадала в бандл — и всё равно не показывалась, потому что
 * правило `.payment-page > p {display:none !important}` из
 * `payment-copy-cleanup.css` скрывает на экране оплаты любой прямой абзац.
 * Поэтому здесь запускается настоящий браузер по собранному production-бандлу,
 * ответы API подменяются теми же полями, что отдаёт backend, и проверяется
 * вычисленный стиль элемента, а не наличие строки в файле.
 *
 * Запуск: node --test miniapp/test/dom (нужен собранный dist и Chromium).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const BASE = process.env.KORGAN_UI_BASE || 'http://127.0.0.1:4173';
const CHROME = process.env.KORGAN_CHROME || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
/** Фоновые службы браузера в этой среде недоступны и только тормозят запуск. */
const ARGS = [
  '--disable-background-networking',
  '--disable-component-update',
  '--disable-sync',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-domain-reliability',
  '--disable-features=OptimizationHints,MediaRouter',
];

/**
 * Проверка требует браузера и поднятого сервера сборки, поэтому в окружении
 * деплоя (где `npm test` выполняется до `npm run build` и без Chromium) она
 * пропускается, а не роняет выкладку. Запуск вручную:
 *
 *   cd miniapp && npm run build && node server.mjs &
 *   npm run test:ui
 */
async function environment() {
  if (!existsSync(CHROME)) return { ready: false, reason: `нет Chromium: ${CHROME}` };
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    return { ready: false, reason: 'пакет playwright не установлен' };
  }
  try {
    const response = await fetch(BASE, { signal: AbortSignal.timeout(2000) });
    if (!response.ok) return { ready: false, reason: `сервер сборки ответил ${response.status}` };
  } catch {
    return { ready: false, reason: `сервер сборки не отвечает на ${BASE}` };
  }
  return { ready: true, chromium };
}

/** Версия условий берётся из самого приложения: иначе согласие не совпадёт. */
const TERMS_VERSION = readFileSync(new URL('../../src/main.jsx', import.meta.url), 'utf8')
  .match(/TERMS_VERSION\s*=\s*'([^']+)'/)?.[1] || '';

/** /health — korgan/miniapp_api_v3.py::health. */
const HEALTH = {
  status: 'ok',
  legal_runtime: 'strict_bot',
  word_quality_target: '10/10',
  preliminary_fallback: true,
  storage: 'postgres',
};

/**
 * /miniapp/parity — финальный владелец в этой ветке
 * korgan/miniapp_manual_payment_admin.py::parity поверх ofd → v5 → v4.
 * Провайдера Tole в ветке нет вовсе, подтверждение оплаты ручное.
 */
const PARITY = {
  status: 'ok',
  api_version: '1.0.0',
  legal_runtime: 'strict_bot',
  service_outer: 'ClaimPipelineV2Adapter',
  service_claim_mux: 'ClaimServiceMux',
  service_stable: 'PretrialResponseProductionService',
  word_quality_target: '10/10',
  preliminary_fallback: true,
  consultation_limit_enabled: true,
  free_consultations_per_day: 3,
  consultation_price_kzt: 500,
  document_payments_enabled: true,
  document_price_kzt: 1000,
  document_manual_confirmation: true,
  document_payment_admin_configured: true,
  automatic_receipt_verification: false,
  receipt_verification_mode: 'kaspi_receipt_precheck_then_telegram_admin',
  receipt_ai_decision: false,
  document_types: ['claim', 'contract', 'pretrial', 'pretrial_response', 'response'],
};

/** /miniapp/pricing — korgan/miniapp_api_v4.py::pricing. */
const PRICING = {
  consultation_limit_enabled: true,
  free_consultations_per_day: 3,
  consultation_price_kzt: 500,
  document_price_kzt: 1000,
  document_payments_enabled: true,
  document_manual_confirmation: true,
  is_admin: false,
  kaspi_url: 'https://pay.kaspi.kz/pay/example',
};

/** Поля ровно те, что строит korgan/miniapp_api_v5.py::_payment_payload. */
const PAYMENT = {
  order_id: 4242,
  case_id: 'KOR-ABCDEF123456',
  document_type: 'claim',
  amount_kzt: 1000,
  kaspi_url: 'https://pay.kaspi.kz/pay/example',
  status: 'pending_receipt',
  approval_required: false,
  decision_note: '',
  receipt_accept: ['PDF', 'JPG', 'JPEG', 'PNG', 'WEBP'],
};

/** Поля ровно те, что строит korgan/miniapp_api.py::_public_case. */
function publicCase(overrides = {}) {
  return {
    id: 'KOR-ABCDEF123456',
    document_type: 'claim',
    language: 'ru',
    description: 'Взыскание уплаченной по договору суммы',
    status: 'materials_ready',
    created_at: '2026-09-06T08:00:00+00:00',
    materials_count: 0,
    material_names: [],
    conversation_count: 0,
    has_document: false,
    ...overrides,
  };
}

const READY_CASE = publicCase({
  status: 'document_ready',
  title: 'Исковое заявление о взыскании уплаченной по договору суммы',
  verification_status: 'VERIFIED',
  verification_notes: [],
  quality_score: 10,
  quality_issues: [],
  filing_ready: true,
  release_status: 'verified',
  filename: 'claim.docx',
  has_document: true,
  materials_count: 0,
});

async function openApp({ cases = [], onRoute, chromium } = {}) {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME, args: ARGS });
  const context = await browser.newContext();

  // Внешние адреса (скрипт Telegram, шрифты) в тестовой среде недоступны, и
  // ожидание их загрузки подвесило бы проверку. Страница проверяется в том
  // виде, в каком её собирает production-сборка, без внешних ресурсов.
  await context.route('**/*', async route => {
    const url = route.request().url();
    if (url.startsWith(BASE)) {
      if (new URL(url).pathname === '/health') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(HEALTH) });
      }
      return route.fallback();
    }
    if (url.startsWith('data:') || url.startsWith('blob:')) return route.fallback();
    return route.fulfill({ status: 200, contentType: 'application/javascript', body: '' });
  });

  await context.route('**/miniapp/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (onRoute) {
      const handled = await onRoute(path, json, route);
      if (handled) return;
    }
    if (path.endsWith('/miniapp/parity')) return json(PARITY);
    if (path.endsWith('/miniapp/consent')) return json({ accepted: true, terms_version: TERMS_VERSION });
    if (path.endsWith('/miniapp/pricing')) return json(PRICING);
    if (path.endsWith('/miniapp/cases')) return json({ cases });
    if (path.endsWith('/generation')) return json({ job: null });
    return json({});
  });

  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'test', initDataUnsafe: { user: { id: 1, first_name: 'Test' } }, ready() {}, expand() {}, HapticFeedback: { impactOccurred() {} } } };
  });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.app-shell', { timeout: 20000 });
  return { browser, page, errors };
}

/** Реальный экран оплаты: дело → «Подготовить документ» → ответ payment_required. */
async function openPaymentScreen(chromium) {
  const session = await openApp({
    chromium,
    cases: [publicCase()],
    onRoute: async (path, json) => {
      if (path.endsWith('/documents/generate')) {
        json({ payment_required: true, generation_started: false, payment: PAYMENT });
        return true;
      }
      if (path.includes('/miniapp/cases/')) {
        if (path.endsWith('/generation')) { json({ job: null }); return true; }
        json({ case: publicCase() });
        return true;
      }
      return false;
    },
  });

  const { page } = session;
  await page.getByRole('button', { name: /Мои дела/ }).first().click();
  await page.locator('.case-list-item').first().click();
  await page.locator('button.primary.wide', { hasText: /Подготовить документ/ }).click();
  await page.waitForSelector('.payment-page', { timeout: 15000 });
  return session;
}

test('экран оплаты действительно показывает пояснение под кнопкой Kaspi', async t => {
  const env = await environment();
  if (!env.ready) return t.skip(env.reason);
  const { browser, page, errors } = await openPaymentScreen(env.chromium);
  t.after(() => browser.close());

  // 1. Ветка рендера — та, что реально живёт в production.
  const button = page.locator('.payment-page button.primary.wide', { hasText: 'Оплатить через Kaspi' });
  assert.equal(await button.count(), 1, 'кнопка оплаты не отрисована');

  // 2. Элемент присутствует в DOM.
  const guidance = page.locator('.payment-page .payment-guidance');
  assert.equal(await guidance.count(), 1, 'пояснения нет в DOM');
  assert.match(
    (await guidance.innerText()).trim(),
    /После успешной оплаты система автоматически подтвердит платёж и приступит к подготовке документа\. Обычно это занимает несколько минут\./,
  );

  // 3. Главное: он виден. Именно здесь падала предыдущая «починка».
  assert.equal(await guidance.isVisible(), true, 'пояснение есть в DOM, но скрыто стилями');

  const style = await guidance.evaluate(node => {
    const computed = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return {
      display: computed.display,
      visibility: computed.visibility,
      opacity: computed.opacity,
      height: box.height,
      width: box.width,
    };
  });
  assert.notEqual(style.display, 'none', `display=${style.display}`);
  assert.notEqual(style.visibility, 'hidden');
  assert.ok(Number(style.opacity) > 0, `opacity=${style.opacity}`);
  assert.ok(style.height > 0 && style.width > 0, `размер ${style.width}x${style.height}`);

  // 4. Порядок: пояснение идёт сразу за кнопкой оплаты.
  const order = await page.locator('.payment-page').evaluate(node => {
    const children = [...node.children];
    const buttonIndex = children.findIndex(child => child.matches('button.primary.wide'));
    const guidanceIndex = children.findIndex(child => child.classList.contains('payment-guidance'));
    return { buttonIndex, guidanceIndex };
  });
  assert.ok(order.buttonIndex >= 0 && order.guidanceIndex === order.buttonIndex + 1,
    `порядок элементов: кнопка ${order.buttonIndex}, пояснение ${order.guidanceIndex}`);

  assert.deepEqual(errors, [], 'ошибки в консоли страницы');
});

test('«Мои дела»: готовый документ без материалов не сообщает о незагруженных материалах', async t => {
  const env = await environment();
  if (!env.ready) return t.skip(env.reason);
  const { browser, page } = await openApp({ chromium: env.chromium, cases: [READY_CASE] });
  t.after(() => browser.close());

  await page.getByRole('button', { name: /Мои дела/ }).first().click();
  await page.waitForSelector('.case-list-item', { timeout: 15000 });

  const meta = (await page.locator('.case-list-item small').first().innerText()).trim();
  assert.equal(meta, 'Документ готов · Word', `подпись карточки: ${meta}`);
});

test('«Мои дела»: дело с материалами и документом называет и то, и другое', async t => {
  const env = await environment();
  if (!env.ready) return t.skip(env.reason);
  const { browser, page } = await openApp({
    chromium: env.chromium,
    cases: [{ ...READY_CASE, materials_count: 3, material_names: ['a.pdf', 'b.pdf', 'c.pdf'] }],
  });
  t.after(() => browser.close());

  await page.getByRole('button', { name: /Мои дела/ }).first().click();
  await page.waitForSelector('.case-list-item', { timeout: 15000 });

  const meta = (await page.locator('.case-list-item small').first().innerText()).trim();
  assert.equal(meta, 'Материалов: 3 · Документ готов · Word', `подпись карточки: ${meta}`);
});

test('«Мои дела»: дело без документа по-прежнему сообщает об отсутствии материалов', async t => {
  const env = await environment();
  if (!env.ready) return t.skip(env.reason);
  const { browser, page } = await openApp({ chromium: env.chromium, cases: [publicCase()] });
  t.after(() => browser.close());

  await page.getByRole('button', { name: /Мои дела/ }).first().click();
  await page.waitForSelector('.case-list-item', { timeout: 15000 });

  const meta = (await page.locator('.case-list-item small').first().innerText()).trim();
  assert.equal(meta, 'Материалы не загружены', `подпись карточки: ${meta}`);
});
