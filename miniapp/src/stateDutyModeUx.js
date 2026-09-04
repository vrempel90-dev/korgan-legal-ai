const MODE_ID = 'klt-duty-mode';
const AMOUNT_ID = 'klt-duty-amount';
const NONPROPERTY_ID = 'klt-duty-nonproperty';
const RESULT_ID = 'klt-duty-result';

function labelFor(id) {
  return document.getElementById(id)?.closest('label') || null;
}

function normalizePositiveCount(input) {
  if (!input) return;
  input.min = '1';
  const value = Number(input.value || 0);
  if (!Number.isFinite(value) || value < 1) input.value = '1';
}

export function syncStateDutyMode({ clearResult = false } = {}) {
  const mode = document.getElementById(MODE_ID)?.value;
  const amount = document.getElementById(AMOUNT_ID);
  const nonproperty = document.getElementById(NONPROPERTY_ID);
  if (!mode || !amount || !nonproperty) return false;

  const amountLabel = labelFor(AMOUNT_ID);
  const nonpropertyLabel = labelFor(NONPROPERTY_ID);
  const usesAmount = mode === 'property' || mode === 'mixed';
  const usesNonproperty = mode === 'nonproperty' || mode === 'mixed';

  if (amountLabel) amountLabel.hidden = !usesAmount;
  if (nonpropertyLabel) nonpropertyLabel.hidden = !usesNonproperty;

  amount.required = usesAmount;
  nonproperty.required = usesNonproperty;

  if (!usesAmount) amount.value = '';
  if (!usesNonproperty) {
    nonproperty.value = '0';
    nonproperty.min = '0';
  } else {
    normalizePositiveCount(nonproperty);
  }

  if (clearResult) {
    const result = document.getElementById(RESULT_ID);
    result?.classList.remove('show', 'error');
    if (result) result.textContent = '';
  }
  return true;
}

function install() {
  document.addEventListener('change', event => {
    if (event.target?.id === MODE_ID) syncStateDutyMode({ clearResult: true });
  }, true);

  document.addEventListener('click', event => {
    const id = event.target?.id;
    if (id === 'korgan-legal-tools-button') {
      window.setTimeout(() => syncStateDutyMode(), 0);
    }
    // Capture phase runs before Legal Workspace's button handler. Irrelevant
    // fields are normalized to backend-neutral values before its JSON payload is
    // built, while the visible form shows only fields that apply to the mode.
    if (id === 'klt-duty-submit') syncStateDutyMode();
  }, true);

  window.addEventListener('pageshow', () => window.setTimeout(() => syncStateDutyMode(), 0));
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') install();
