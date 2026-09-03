const API_BASE = String(import.meta.env.VITE_KORGAN_API_BASE || '').replace(/\/$/, '');

function initData() {
  return String(window.Telegram?.WebApp?.initData || '');
}

async function api(path, options = {}) {
  if (!API_BASE) throw new Error('API Mini App не настроен');
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData(),
      ...(options.headers || {}),
    },
  });
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(String(payload.detail || payload.message || `HTTP ${response.status}`));
  return payload;
}

function money(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value || 0)) + ' ₸';
}

function resultBox(id, text, { error = false, sourceUrl = '', sourceLabel = '' } = {}) {
  const box = document.getElementById(id);
  if (!box) return;
  box.classList.toggle('error', error);
  box.classList.add('show');
  box.textContent = text;
  if (sourceUrl) {
    const link = document.createElement('a');
    link.className = 'korgan-legal-tool-source';
    link.href = sourceUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = sourceLabel || 'Открыть официальный источник';
    box.appendChild(document.createElement('br'));
    box.appendChild(link);
  }
}

async function loadCases(select) {
  select.innerHTML = '<option value="">Выберите дело…</option>';
  try {
    const payload = await api('/miniapp/cases');
    for (const item of payload.cases || []) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = String(item.title || item.description || item.document_type || item.id).slice(0, 80);
      select.appendChild(option);
    }
  } catch (error) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = `Не удалось загрузить дела: ${error.message}`;
    select.appendChild(option);
  }
}

function mount() {
  if (document.getElementById('korgan-legal-tools-button')) return;

  const button = document.createElement('button');
  button.id = 'korgan-legal-tools-button';
  button.className = 'korgan-legal-tools-button';
  button.type = 'button';
  button.textContent = '⚖ Юр. инструменты';

  const backdrop = document.createElement('div');
  backdrop.className = 'korgan-legal-tools-backdrop';
  backdrop.innerHTML = `
    <section class="korgan-legal-tools-sheet" role="dialog" aria-modal="true" aria-label="Юридические инструменты KORGAN">
      <div class="korgan-legal-tools-head">
        <div><h2>Юридические инструменты</h2><p>Расчёты выполняет код. Правовые выводы — только по проверенным источникам РК.</p></div>
        <button class="korgan-legal-tools-close" type="button" aria-label="Закрыть">×</button>
      </div>

      <article class="korgan-legal-tool-card">
        <h3>Госпошлина</h3>
        <p class="hint">Обычный гражданский имущественный, неимущественный или смешанный иск. Льготы и специальные категории проверяются отдельно.</p>
        <div class="korgan-legal-tool-grid">
          <label>Тип требования
            <select id="klt-duty-mode"><option value="property">Имущественное</option><option value="nonproperty">Неимущественное</option><option value="mixed">Смешанное</option></select>
          </label>
          <label>Истец
            <select id="klt-duty-claimant"><option value="individual">Физлицо / ИП</option><option value="legal_entity">Юрлицо</option></select>
          </label>
          <label>Цена иска, ₸<input id="klt-duty-amount" inputmode="numeric" type="number" min="0" step="1" placeholder="5000000"></label>
          <label>Неимущественных требований<input id="klt-duty-nonproperty" inputmode="numeric" type="number" min="0" max="50" step="1" value="0"></label>
        </div>
        <button id="klt-duty-submit" class="korgan-legal-tool-action" type="button">Рассчитать госпошлину</button>
        <div id="klt-duty-result" class="korgan-legal-tool-result"></div>
      </article>

      <article class="korgan-legal-tool-card">
        <h3>Неустойка по ст. 353 ГК РК</h3>
        <p class="hint">Законная ответственность за неправомерное пользование чужими деньгами. Ставка берётся из подтверждённого справочника НБ РК.</p>
        <div class="korgan-legal-tool-grid">
          <label class="wide">Основной долг, ₸<input id="klt-penalty-principal" inputmode="numeric" type="number" min="1" step="1" placeholder="1000000"></label>
          <label>Начало просрочки<input id="klt-penalty-start" type="date"></label>
          <label>Конец периода<input id="klt-penalty-end" type="date"></label>
          <label class="wide">Дата базовой ставки<input id="klt-penalty-rate-date" type="date"><span>Если не указана — используется начало периода.</span></label>
        </div>
        <button id="klt-penalty-submit" class="korgan-legal-tool-action" type="button">Рассчитать неустойку</button>
        <div id="klt-penalty-result" class="korgan-legal-tool-result"></div>
      </article>

      <article class="korgan-legal-tool-card">
        <h3>Stress Test позиции</h3>
        <p class="hint">KORGAN выступает как оппонент: ищет слабые места, доказательственные и процессуальные риски и проверяет правовые выводы по действующим нормам РК.</p>
        <div class="korgan-legal-tool-grid">
          <label class="wide">Дело<select id="klt-stress-case"><option value="">Выберите дело…</option></select></label>
          <label class="wide">На что обратить особое внимание<textarea id="klt-stress-focus" placeholder="Например: срок исковой давности, доказательство поставки, размер неустойки…"></textarea></label>
        </div>
        <button id="klt-stress-submit" class="korgan-legal-tool-action" type="button">Проверить позицию</button>
        <div id="klt-stress-result" class="korgan-legal-tool-result"></div>
      </article>
    </section>`;

  document.body.append(button, backdrop);
  const close = () => backdrop.classList.remove('open');
  button.addEventListener('click', async () => {
    backdrop.classList.add('open');
    await loadCases(document.getElementById('klt-stress-case'));
  });
  backdrop.querySelector('.korgan-legal-tools-close')?.addEventListener('click', close);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(); });

  document.getElementById('klt-duty-submit')?.addEventListener('click', async (event) => {
    const submit = event.currentTarget;
    submit.disabled = true;
    try {
      const payload = await api('/miniapp/legal-workspace/state-duty', {
        method: 'POST',
        body: JSON.stringify({
          mode: document.getElementById('klt-duty-mode').value,
          claimant_type: document.getElementById('klt-duty-claimant').value,
          amount_kzt: Number(document.getElementById('klt-duty-amount').value || 0),
          nonproperty_demands: Number(document.getElementById('klt-duty-nonproperty').value || 0),
        }),
      });
      resultBox('klt-duty-result', `Госпошлина: ${money(payload.amount_kzt)}\n${payload.warning || ''}`, {
        sourceUrl: payload.source_url,
        sourceLabel: payload.source || 'Налоговый кодекс РК',
      });
    } catch (error) {
      resultBox('klt-duty-result', error.message, { error: true });
    } finally { submit.disabled = false; }
  });

  document.getElementById('klt-penalty-submit')?.addEventListener('click', async (event) => {
    const submit = event.currentTarget;
    submit.disabled = true;
    try {
      const rateDate = document.getElementById('klt-penalty-rate-date').value;
      const payload = await api('/miniapp/legal-workspace/late-penalty-353', {
        method: 'POST',
        body: JSON.stringify({
          principal_kzt: Number(document.getElementById('klt-penalty-principal').value || 0),
          start_date: document.getElementById('klt-penalty-start').value,
          end_date: document.getElementById('klt-penalty-end').value,
          rate_date: rateDate || null,
        }),
      });
      if (payload.status !== 'calculated') {
        resultBox('klt-penalty-result', payload.reason || 'Ставка требует проверки', {
          error: true, sourceUrl: payload.source_url, sourceLabel: payload.source,
        });
      } else {
        resultBox('klt-penalty-result', `Неустойка: ${money(payload.amount_kzt)}\nДней: ${payload.days}\nБазовая ставка: ${payload.base_rate_percent}%\n${payload.formula}`, {
          sourceUrl: payload.source_url,
          sourceLabel: payload.source,
        });
      }
    } catch (error) {
      resultBox('klt-penalty-result', error.message, { error: true });
    } finally { submit.disabled = false; }
  });

  document.getElementById('klt-stress-submit')?.addEventListener('click', async (event) => {
    const submit = event.currentTarget;
    submit.disabled = true;
    resultBox('klt-stress-result', 'Проверяю позицию и актуальные нормы РК…');
    try {
      const payload = await api('/miniapp/legal-workspace/stress-test', {
        method: 'POST',
        body: JSON.stringify({
          case_id: document.getElementById('klt-stress-case').value,
          focus: document.getElementById('klt-stress-focus').value,
          language: document.documentElement.lang === 'kk' ? 'kk' : 'ru',
        }),
      });
      const sources = (payload.sources || []).length ? `\n\nИсточники:\n${payload.sources.join('\n')}` : '';
      resultBox('klt-stress-result', `${payload.answer || ''}${sources}`);
    } catch (error) {
      resultBox('klt-stress-result', error.message, { error: true });
    } finally { submit.disabled = false; }
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();
