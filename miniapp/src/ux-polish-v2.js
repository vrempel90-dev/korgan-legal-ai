import { createDocumentAccess, sendDocumentToTelegram } from './document-access';

const SOUND_KEY = 'korgan-notification-sound-v1';
const HAPTIC_KEY = 'korgan-notification-haptic-v1';
const dismissedNotices = new Map();
const processedToasts = new WeakSet();
const workflowState = new Map();
const accessCache = new Map();
let audioContext = null;
let scheduled = false;

function isOn(key) {
  try { return localStorage.getItem(key) !== '0'; } catch { return true; }
}
function setOn(key, value) {
  try { localStorage.setItem(key, value ? '1' : '0'); } catch {}
}
function isKazakh() {
  try {
    const raw = localStorage.getItem('korgan-miniapp-state-v1');
    const state = raw ? JSON.parse(raw) : null;
    return document.documentElement.lang === 'kk' || state?.language === 'kk';
  } catch { return document.documentElement.lang === 'kk'; }
}

function postTelegramEvent(type, payload) {
  try {
    const proxy = window.TelegramWebviewProxy;
    if (!proxy || typeof proxy.postEvent !== 'function') return false;
    proxy.postEvent(type, JSON.stringify(payload ?? ''));
    return true;
  } catch { return false; }
}

function haptic(type = 'success') {
  if (!isOn(HAPTIC_KEY)) return;
  try {
    const api = window.Telegram?.WebApp?.HapticFeedback;
    if (api?.notificationOccurred) {
      api.notificationOccurred(type === 'error' ? 'error' : type === 'warning' ? 'warning' : 'success');
      return;
    }
  } catch {}
  postTelegramEvent('web_app_trigger_haptic_feedback', {
    type: 'notification',
    notification_type: type === 'error' ? 'error' : type === 'warning' ? 'warning' : 'success',
  });
}

function lightHaptic() {
  if (!isOn(HAPTIC_KEY)) return;
  try {
    const api = window.Telegram?.WebApp?.HapticFeedback;
    if (api?.impactOccurred) { api.impactOccurred('light'); return; }
  } catch {}
  postTelegramEvent('web_app_trigger_haptic_feedback', { type: 'impact', impact_style: 'light' });
}

function ensureAudio() {
  try {
    if (!audioContext) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return null;
      audioContext = new AudioContextClass();
    }
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
    return audioContext;
  } catch { return null; }
}

function playSound(tone = 'success') {
  if (!isOn(SOUND_KEY)) return;
  const ctx = ensureAudio();
  if (!ctx) return;
  try {
    const now = ctx.currentTime;
    const notes = tone === 'error' ? [310, 230] : [660, 880];
    notes.forEach((frequency, index) => {
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      const start = now + index * 0.09;
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(frequency, start);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.055, start + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.075);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.085);
    });
  } catch {}
}

// Prime WebAudio only after a real user gesture; failures are harmless.
document.addEventListener('pointerdown', () => { if (isOn(SOUND_KEY)) ensureAudio(); }, { capture: true, passive: true });

function toastStack() {
  let stack = document.querySelector('.korgan-polish-toast-stack');
  if (stack) return stack;
  stack = document.createElement('div');
  stack.className = 'korgan-polish-toast-stack';
  stack.setAttribute('aria-live', 'polite');
  document.body.appendChild(stack);
  return stack;
}

function showToast(message, { tone = 'success', duration = 3200, sound = false } = {}) {
  const card = document.createElement('div');
  card.className = `korgan-polish-toast ${tone}`;
  const icon = document.createElement('span');
  icon.className = 'korgan-polish-toast-icon';
  icon.textContent = tone === 'error' ? '!' : tone === 'info' ? 'i' : '✓';
  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'korgan-polish-toast-close';
  close.setAttribute('aria-label', isKazakh() ? 'Жабу' : 'Закрыть');
  close.textContent = '×';
  card.append(icon, text, close);
  const dismiss = () => {
    if (!card.isConnected || card.classList.contains('is-leaving')) return;
    card.classList.add('is-leaving');
    window.setTimeout(() => card.remove(), 180);
  };
  close.addEventListener('click', dismiss);
  toastStack().prepend(card);
  window.setTimeout(dismiss, duration);
  if (tone === 'error') haptic('error'); else if (tone === 'success') haptic('success');
  if (sound) playSound(tone === 'error' ? 'error' : 'success');
  return card;
}

function shortBrand() {
  document.title = 'KORGAN';
  document.querySelectorAll('h1,h2,h3,.subbar strong,.brand,.app-brand,.brand-name').forEach((node) => {
    if (node.childElementCount > 0 && !node.matches('h1,h2,h3')) return;
    const value = node.textContent || '';
    if (value.includes('KORGAN Legal AI')) node.textContent = value.replaceAll('KORGAN Legal AI', 'KORGAN');
  });
}

function transientReactNotices() {
  const now = Date.now();
  for (const [text, expires] of dismissedNotices) if (expires < now) dismissedNotices.delete(text);

  document.querySelectorAll('.warning-note').forEach((notice) => {
    if (notice.classList.contains('left-note') || notice.closest('.analysis-card.manual-card')) return;
    const text = (notice.textContent || '').trim();
    if (!text) return;
    if (dismissedNotices.has(text)) {
      notice.classList.add('korgan-notice-hidden');
      return;
    }
    if (notice.dataset.korganTransient === '1') return;
    notice.dataset.korganTransient = '1';
    notice.classList.add('korgan-transient-notice');
    const delay = /ошиб|failed|недоступ|қате/i.test(text) ? 5000 : 3500;
    window.setTimeout(() => {
      dismissedNotices.set(text, Date.now() + 60_000);
      notice.classList.add('is-leaving');
      window.setTimeout(() => notice.classList.add('korgan-notice-hidden'), 180);
    }, delay);
  });
}

function normalizeMotionToasts() {
  document.querySelectorAll('.korgan-doc-toast').forEach((toast) => {
    if (processedToasts.has(toast)) return;
    processedToasts.add(toast);
    const tone = toast.classList.contains('error') ? 'error' : toast.classList.contains('payment') ? 'warning' : 'success';
    const duration = tone === 'error' || tone === 'warning' ? 5000 : 3500;
    if (tone === 'success') { haptic('success'); playSound('success'); }
    if (tone === 'error') { haptic('error'); playSound('error'); }
    window.setTimeout(() => {
      if (!toast.isConnected) return;
      toast.classList.add('is-leaving');
      window.setTimeout(() => toast.remove(), 180);
    }, duration);
  });
}

function caseIdFrom(element) {
  const ready = element?.closest?.('[data-case-id]');
  const fromDataset = ready?.dataset?.caseId;
  if (fromDataset && /^KOR-/i.test(fromDataset)) return fromDataset.toUpperCase();
  const page = element?.closest?.('main.page') || document.querySelector('main.page');
  const header = page?.closest('.app-shell')?.querySelector('.subbar strong')?.textContent || '';
  const match = header.match(/KOR-[A-Z0-9]+/i);
  if (match) return match[0].toUpperCase();
  const progressId = page?.querySelector('.korgan-document-progress[data-case-id]')?.dataset?.caseId;
  return progressId ? progressId.toUpperCase() : '';
}

function cachedAccess(caseId) {
  if (!caseId) return Promise.reject(new Error('Дело не найдено'));
  let entry = accessCache.get(caseId);
  const now = Date.now();
  if (entry && entry.expiresAt > now + 15_000) return entry.promise;
  const promise = createDocumentAccess(caseId).then((access) => {
    const expiresAt = Number(access?.expires_at || 0) * 1000;
    accessCache.set(caseId, { promise: Promise.resolve(access), expiresAt });
    return access;
  }).catch((error) => {
    accessCache.delete(caseId);
    throw error;
  });
  entry = { promise, expiresAt: now + 120_000 };
  accessCache.set(caseId, entry);
  return promise;
}

function requestNativeDownload(access) {
  const tg = window.Telegram?.WebApp;
  if (tg && typeof tg.downloadFile === 'function') {
    return new Promise((resolve) => {
      try {
        tg.downloadFile({ url: access.download_url, file_name: access.filename }, (accepted) => resolve(Boolean(accepted)));
      } catch { resolve(false); }
    });
  }
  const sent = postTelegramEvent('web_app_request_file_download', { url: access.download_url, file_name: access.filename });
  return Promise.resolve(sent);
}

async function downloadDocument(button, caseId) {
  if (!caseId || button.dataset.korganBusy === '1') return;
  button.dataset.korganBusy = '1';
  button.classList.add('is-busy');
  button.disabled = true;
  try {
    const access = await cachedAccess(caseId);
    const requested = await requestNativeDownload(access);
    if (requested) {
      showToast(isKazakh() ? 'Жүктеу басталды' : 'Скачивание началось', { tone: 'success', sound: true });
      return;
    }
    const delivery = await sendDocumentToTelegram(caseId);
    showToast(delivery?.message || (isKazakh() ? 'DOCX Telegram чатына жіберілді' : 'DOCX отправлен в чат Telegram'), { tone: 'success', sound: true, duration: 4200 });
  } catch (error) {
    try {
      const delivery = await sendDocumentToTelegram(caseId);
      showToast(delivery?.message || (isKazakh() ? 'DOCX Telegram чатына жіберілді' : 'DOCX отправлен в чат Telegram'), { tone: 'success', sound: true, duration: 4200 });
    } catch (fallbackError) {
      showToast(fallbackError?.message || error?.message || (isKazakh() ? 'Құжатты жүктеу мүмкін болмады' : 'Не удалось скачать документ'), { tone: 'error', sound: true, duration: 5200 });
    }
  } finally {
    button.dataset.korganBusy = '0';
    button.classList.remove('is-busy');
    button.disabled = false;
  }
}

async function openDocument(button, caseId) {
  if (!caseId || button.dataset.korganBusy === '1') return;
  button.dataset.korganBusy = '1';
  button.classList.add('is-busy');
  button.disabled = true;
  try {
    const access = await cachedAccess(caseId);
    const url = access.preview_url;
    let opened = false;
    try {
      const tg = window.Telegram?.WebApp;
      if (tg && typeof tg.openLink === 'function') { tg.openLink(url); opened = true; }
    } catch {}
    if (!opened) opened = postTelegramEvent('web_app_open_link', { url });
    if (!opened) window.location.assign(url);
    lightHaptic();
  } catch (error) {
    showToast(error?.message || (isKazakh() ? 'Құжатты ашу мүмкін болмады' : 'Не удалось открыть документ'), { tone: 'error', sound: true });
  } finally {
    button.dataset.korganBusy = '0';
    button.classList.remove('is-busy');
    button.disabled = false;
  }
}

function isDownloadText(text) {
  return /скачать\s*docx|docx\s*жүктеу|құжат.*жүктеу/i.test(text);
}

function enhanceDocumentActions() {
  document.querySelectorAll('button').forEach((button) => {
    const text = (button.textContent || '').trim();
    if (!isDownloadText(text)) return;
    button.classList.add('korgan-native-download');
    const caseId = caseIdFrom(button);
    if (caseId) cachedAccess(caseId).catch(() => {});

    const container = button.parentElement;
    if (!container || container.querySelector('.korgan-open-document')) return;
    const open = document.createElement('button');
    open.type = 'button';
    open.className = button.classList.contains('korgan-inline-ready-action')
      ? 'korgan-inline-ready-action korgan-open-document'
      : 'secondary wide korgan-open-document';
    open.textContent = isKazakh() ? 'Ашу' : 'Открыть';
    button.insertAdjacentElement('afterend', open);
  });

  document.querySelectorAll('.korgan-inline-ready-card[data-case-id]').forEach((card) => {
    const caseId = card.dataset.caseId;
    if (caseId) cachedAccess(caseId).catch(() => {});
    if (card.querySelector('.korgan-open-document')) return;
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'korgan-inline-ready-action korgan-open-document';
    open.textContent = isKazakh() ? 'Ашу' : 'Открыть';
    card.appendChild(open);
  });
}

function enhanceWorkflow() {
  document.querySelectorAll('.korgan-document-progress[data-case-id]').forEach((panel) => {
    const caseId = panel.dataset.caseId || '';
    const doneRows = Array.from(panel.querySelectorAll('.korgan-progress-step.is-done'));
    const doneCount = doneRows.length;
    panel.querySelectorAll('.korgan-progress-step').forEach((row, index) => {
      const badge = row.querySelector('.korgan-progress-index');
      if (!badge) return;
      if (!badge.dataset.korganNumber) badge.dataset.korganNumber = String(index + 1);
      badge.textContent = row.classList.contains('is-done') ? '✓' : badge.dataset.korganNumber;
    });
    if (!workflowState.has(caseId)) {
      workflowState.set(caseId, doneCount);
    } else {
      const previous = workflowState.get(caseId) || 0;
      if (doneCount > previous) {
        showToast(isKazakh() ? `${doneCount}-қадам аяқталды` : `Шаг ${doneCount} завершён`, { tone: 'success', duration: 2200, sound: false });
        lightHaptic();
      }
      workflowState.set(caseId, doneCount);
    }
  });
}

function settingRow(label, description, key) {
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'korgan-notification-setting';
  const copy = document.createElement('span');
  copy.className = 'korgan-notification-copy';
  const strong = document.createElement('strong'); strong.textContent = label;
  const small = document.createElement('small'); small.textContent = description;
  copy.append(strong, small);
  const toggle = document.createElement('span');
  toggle.className = `korgan-toggle${isOn(key) ? ' is-on' : ''}`;
  toggle.setAttribute('aria-hidden', 'true');
  row.append(copy, toggle);
  row.setAttribute('aria-pressed', isOn(key) ? 'true' : 'false');
  row.addEventListener('click', () => {
    const next = !isOn(key);
    setOn(key, next);
    toggle.classList.toggle('is-on', next);
    row.setAttribute('aria-pressed', next ? 'true' : 'false');
    if (key === SOUND_KEY && next) playSound('success');
    if (key === HAPTIC_KEY && next) lightHaptic();
  });
  return row;
}

function notificationSettings() {
  const profile = document.querySelector('main.page .profile-card');
  if (!profile || profile.parentElement?.querySelector('.korgan-notification-settings')) return;
  const kk = isKazakh();
  const section = document.createElement('section');
  section.className = 'korgan-notification-settings';
  const kicker = document.createElement('span');
  kicker.className = 'section-kicker';
  kicker.textContent = kk ? 'ХАБАРЛАМАЛАР' : 'УВЕДОМЛЕНИЯ';
  section.append(kicker);
  section.append(settingRow(kk ? 'Хабарлама дыбысы' : 'Звук уведомлений', kk ? 'Маңызды оқиғалар үшін қысқа дыбыс' : 'Короткий звук для важных событий', SOUND_KEY));
  section.append(settingRow(kk ? 'Діріл' : 'Виброотклик', kk ? 'Telegram қолдайтын құрылғыларда' : 'На устройствах, где Telegram это поддерживает', HAPTIC_KEY));
  const info = document.createElement('p');
  info.className = 'korgan-notification-info';
  info.textContent = kk ? 'Қалқымалы хабарламалар бірнеше секундтан кейін автоматты түрде жоғалады.' : 'Всплывающие уведомления автоматически исчезают через несколько секунд.';
  section.append(info);
  profile.insertAdjacentElement('afterend', section);
}

function apply() {
  shortBrand();
  transientReactNotices();
  normalizeMotionToasts();
  enhanceDocumentActions();
  enhanceWorkflow();
  notificationSettings();
}
function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; apply(); });
}

document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target.closest('button') : null;
  if (!target) return;
  const text = (target.textContent || '').trim();
  if (target.classList.contains('korgan-open-document')) {
    const caseId = caseIdFrom(target);
    if (!caseId) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openDocument(target, caseId);
    return;
  }
  if (isDownloadText(text)) {
    const caseId = caseIdFrom(target);
    if (!caseId) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    downloadDocument(target, caseId);
  }
}, { capture: true });

const observer = new MutationObserver(schedule);
function start() {
  apply();
  observer.observe(document.getElementById('root') || document.body, { childList: true, subtree: true, characterData: true });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
