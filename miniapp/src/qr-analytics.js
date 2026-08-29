const API_BASE = import.meta.env.VITE_KORGAN_API_BASE || '';
const SOURCE_STORAGE_KEY = 'korgan:acquisition-source:v1';
const SOURCE_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const SOURCE_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const ALLOWED_EVENTS = new Set([
  'qr_open',
  'ai_lawyer_open',
  'document_start',
  'payment_confirmed',
]);

function safeStorage(kind = 'localStorage') {
  try {
    return window[kind] || null;
  } catch {
    return null;
  }
}

function normalizeSource(value) {
  const source = String(value || '').trim().toLowerCase();
  return SOURCE_RE.test(source) ? source : '';
}

function initData() {
  return window.Telegram?.WebApp?.initData || window.__KORGAN_TG_INIT_DATA__ || '';
}

function sourceFromInitData(raw) {
  try {
    return normalizeSource(new URLSearchParams(String(raw || '')).get('start_param'));
  } catch {
    return '';
  }
}

function sourceFromHash() {
  try {
    const raw = String(location.hash || '').replace(/^#/, '');
    const query = raw.includes('?') ? raw.slice(raw.indexOf('?') + 1) : raw;
    return normalizeSource(new URLSearchParams(query).get('tgWebAppStartParam'));
  } catch {
    return '';
  }
}

function directSource() {
  return normalizeSource(window.Telegram?.WebApp?.initDataUnsafe?.start_param)
    || sourceFromHash()
    || sourceFromInitData(initData());
}

function readStoredSource() {
  const storage = safeStorage();
  if (!storage) return '';
  try {
    const item = JSON.parse(storage.getItem(SOURCE_STORAGE_KEY) || '{}');
    const source = normalizeSource(item?.source);
    const savedAt = Number(item?.saved_at || 0);
    if (!source || !savedAt || Date.now() - savedAt > SOURCE_TTL_MS) {
      storage.removeItem(SOURCE_STORAGE_KEY);
      return '';
    }
    return source;
  } catch {
    return '';
  }
}

function persistSource(source) {
  const normalized = normalizeSource(source);
  const storage = safeStorage();
  if (!normalized || !storage) return;
  try {
    storage.setItem(SOURCE_STORAGE_KEY, JSON.stringify({ source: normalized, saved_at: Date.now() }));
  } catch {}
}

export function getAcquisitionSource() {
  const direct = directSource();
  if (direct) {
    persistSource(direct);
    return direct;
  }
  return readStoredSource();
}

async function postEvent(event, source) {
  if (!API_BASE || !ALLOWED_EVENTS.has(event)) return false;
  const rawInitData = initData();
  if (!rawInitData) return false;
  try {
    const response = await fetch(`${API_BASE}/miniapp/analytics/event`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': rawInitData,
      },
      body: JSON.stringify({ event, source }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function trackAcquisitionEvent(event) {
  if (!ALLOWED_EVENTS.has(event)) return false;
  const source = getAcquisitionSource();
  if (!source) return false;
  return postEvent(event, source);
}

async function trackDirectOpen(attempt = 0) {
  const source = directSource();
  if (!source) return;
  persistSource(source);
  const session = safeStorage('sessionStorage');
  const key = `korgan:acquisition-open:${source}`;
  try {
    if (session?.getItem(key) === '1') return;
  } catch {}

  const ok = await postEvent('qr_open', source);
  if (ok) {
    try { session?.setItem(key, '1'); } catch {}
    return;
  }
  if (attempt < 3) window.setTimeout(() => trackDirectOpen(attempt + 1), 900 * (attempt + 1));
}

function installActionTracking() {
  document.addEventListener('click', event => {
    const card = event.target?.closest?.('.action-card');
    if (!card) return;
    if (card.querySelector('.action-icon.consult')) {
      void trackAcquisitionEvent('ai_lawyer_open');
    } else if (card.querySelector('.action-icon.document')) {
      void trackAcquisitionEvent('document_start');
    }
  }, { capture: true });
}

function ensureAdminStyles() {
  if (document.getElementById('korgan-qr-analytics-style')) return;
  const style = document.createElement('style');
  style.id = 'korgan-qr-analytics-style';
  style.textContent = `
    .korgan-admin-qr-analytics{margin:14px 0;padding:16px;border:1px solid rgba(201,162,39,.18);border-radius:18px;background:#111820;box-shadow:0 14px 34px rgba(0,0,0,.18)}
    .korgan-admin-qr-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:13px}
    .korgan-admin-qr-head strong{color:#f2efe8;font-size:15px;line-height:1.2}
    .korgan-admin-qr-head span{color:#c9a227;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
    .korgan-admin-qr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}
    .korgan-admin-qr-metric{min-width:0;padding:10px 6px;border:1px solid rgba(255,255,255,.055);border-radius:13px;background:#0c1218;text-align:center}
    .korgan-admin-qr-metric b{display:block;color:#f2efe8;font-size:18px;line-height:1.1;font-variant-numeric:tabular-nums}
    .korgan-admin-qr-metric small{display:block;margin-top:5px;color:#7f8993;font-size:8.5px;line-height:1.2}
    .korgan-admin-qr-conversion{margin:11px 2px 0;color:#8c97a1;font-size:10px;line-height:1.35}
    .korgan-admin-qr-conversion b{color:#50cfa0}
  `;
  document.head.append(style);
}

let adminAccess = 'unknown';
let lastAdminFetchAt = 0;
let adminFetchInFlight = false;

function removeAdminCard() {
  document.querySelectorAll('.korgan-admin-qr-analytics').forEach(node => node.remove());
}

function renderAdminSummary(profile, payload) {
  removeAdminCard();
  ensureAdminStyles();
  const funnel = payload?.funnel || {};
  const metric = event => Number(funnel?.[event]?.unique_users || 0);
  const card = document.createElement('section');
  card.className = 'korgan-admin-qr-analytics';
  card.innerHTML = `
    <div class="korgan-admin-qr-head"><strong>QR-аналитика</strong><span>${Number(payload?.days || 30)} дней</span></div>
    <div class="korgan-admin-qr-grid">
      <div class="korgan-admin-qr-metric"><b>${metric('qr_open')}</b><small>Открыли</small></div>
      <div class="korgan-admin-qr-metric"><b>${metric('ai_lawyer_open')}</b><small>AI-юрист</small></div>
      <div class="korgan-admin-qr-metric"><b>${metric('document_start')}</b><small>Документ</small></div>
      <div class="korgan-admin-qr-metric"><b>${metric('payment_confirmed')}</b><small>Оплатили</small></div>
    </div>
    <div class="korgan-admin-qr-conversion">Конверсия QR → оплата: <b>${Number(payload?.conversion_percent?.payment || 0).toFixed(1)}%</b></div>
  `;
  profile.insertAdjacentElement('afterend', card);
}

async function syncAdminSummary() {
  const profile = document.querySelector('main.page > .profile-card');
  if (!profile) {
    removeAdminCard();
    return;
  }
  if (adminAccess === 'forbidden' || adminFetchInFlight || !API_BASE || !initData()) return;
  if (document.querySelector('.korgan-admin-qr-analytics') && Date.now() - lastAdminFetchAt < 60000) return;

  adminFetchInFlight = true;
  try {
    const response = await fetch(`${API_BASE}/miniapp/admin/analytics/acquisition?source=qr&days=30`, {
      headers: { 'X-Telegram-Init-Data': initData() },
    });
    lastAdminFetchAt = Date.now();
    if (response.status === 403) {
      adminAccess = 'forbidden';
      removeAdminCard();
      return;
    }
    if (!response.ok) return;
    const payload = await response.json().catch(() => null);
    if (!payload?.ok) return;
    adminAccess = 'allowed';
    renderAdminSummary(profile, payload);
  } catch {
    // Analytics must never affect the client workflow.
  } finally {
    adminFetchInFlight = false;
  }
}

function installAdminProfileObserver() {
  const observer = new MutationObserver(() => { void syncAdminSummary(); });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.setTimeout(() => { void syncAdminSummary(); }, 800);
}

installActionTracking();
installAdminProfileObserver();
window.setTimeout(() => { void trackDirectOpen(); }, 250);
window.__KORGAN_TRACK_ACQUISITION__ = trackAcquisitionEvent;
