const APPROVED_HEADINGS = new Set(['Оплата подтверждена', 'Төлем расталды']);
const START_LABELS = new Set([
  'Подготовить оплаченный документ',
  'Төленген құжатты дайындау',
]);

export function shouldAutostartPaidGeneration({ approved, heading, label, disabled = false } = {}) {
  if (!approved || disabled) return false;
  return APPROVED_HEADINGS.has(String(heading || '').trim())
    && START_LABELS.has(String(label || '').trim());
}

function approvedPaymentContext() {
  const page = document.querySelector('.payment-page');
  if (!page) return null;
  const approved = Boolean(page.querySelector('.payment-stage-icon.approved'));
  const heading = page.querySelector('h1')?.textContent?.trim() || '';
  const buttons = Array.from(page.querySelectorAll('button.primary.wide'));
  const button = buttons.find(candidate => START_LABELS.has(candidate.textContent?.trim() || '')) || null;
  const order = page.querySelector('.section-kicker')?.textContent?.trim() || '';
  return { page, approved, heading, button, order };
}

export function installPaidGenerationAutostart() {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return () => {};

  let lastTriggeredOrder = '';
  let scheduled = false;

  const run = () => {
    scheduled = false;
    const context = approvedPaymentContext();
    if (!context) {
      lastTriggeredOrder = '';
      return;
    }
    const { approved, heading, button, order } = context;
    const label = button?.textContent?.trim() || '';
    if (!shouldAutostartPaidGeneration({ approved, heading, label, disabled: button?.disabled })) return;

    const key = order || `${heading}:${label}`;
    if (lastTriggeredOrder === key) return;
    lastTriggeredOrder = key;

    // The backend has already started (or resumed) the durable job. Clicking
    // the legacy button only moves the existing React UI straight into its
    // generation screen; it does not create a second job or a second payment.
    button.style.visibility = 'hidden';
    button.setAttribute('aria-hidden', 'true');
    queueMicrotask(() => button.click());
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(run);
  };

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true });
  schedule();
  return () => observer.disconnect();
}

if (typeof document !== 'undefined') installPaidGenerationAutostart();
