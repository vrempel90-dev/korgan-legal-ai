const APP_STATE_KEY = 'korgan-miniapp-state-v1';

const COPY = {
  ru: {
    hint: 'Если дату не выбирать, KORGAN использует дату окончания периода — обычно это дата подачи иска.',
    needs: 'На выбранную дату актуальная базовая ставка ещё не подтверждена. KORGAN не подставляет старую ставку. Повторите расчёт после подтверждения ставки.',
  },
  kk: {
    hint: 'Күнді таңдамаған жағдайда KORGAN кезеңнің аяқталу күнін қолданады — әдетте бұл талап арыз берілетін күн.',
    needs: 'Таңдалған күнге қолданыстағы базалық мөлшерлеме әлі расталмаған. KORGAN ескі мөлшерлемені қоймайды. Мөлшерлеме расталғаннан кейін есепті қайталаңыз.',
  },
};

function language() {
  try {
    return JSON.parse(localStorage.getItem(APP_STATE_KEY) || '{}')?.language === 'kk' ? 'kk' : 'ru';
  } catch {
    return 'ru';
  }
}

function applyHint() {
  const input = document.getElementById('klt-penalty-rate-date');
  const span = input?.parentElement?.querySelector('span');
  if (span) span.textContent = COPY[language()].hint;
}

function watchResult() {
  const started = Date.now();
  const timer = window.setInterval(() => {
    const box = document.getElementById('klt-penalty-result');
    if (!box || Date.now() - started > 32000) {
      window.clearInterval(timer);
      return;
    }
    if (!box.classList.contains('show')) return;
    window.clearInterval(timer);
    const text = String(box.childNodes?.[0]?.textContent || box.textContent || '').trim();
    if (/^(?:Ставка требует проверки|Мөлшерлемені тексеру қажет)$/i.test(text)) {
      // Preserve any official-source link that Legal Workspace already appended.
      const first = box.firstChild;
      if (first?.nodeType === Node.TEXT_NODE) first.textContent = COPY[language()].needs;
      else box.insertBefore(document.createTextNode(COPY[language()].needs), box.firstChild || null);
    }
  }, 120);
}

function install() {
  document.addEventListener('click', event => {
    const id = event.target?.id;
    if (id === 'korgan-legal-tools-button') window.setTimeout(applyHint, 20);
    if (id === 'klt-penalty-submit') {
      applyHint();
      watchResult();
    }
  }, true);
  window.addEventListener('pageshow', () => window.setTimeout(applyHint, 20));
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') install();
