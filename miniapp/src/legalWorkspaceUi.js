import { createApiTransport } from './apiTransport.js';
import { safeHttpsUrl } from './safeExternalUrl.js';

const API_BASE = String(import.meta.env.VITE_KORGAN_API_BASE || '').replace(/\/$/, '');
const APP_STATE_KEY = 'korgan-miniapp-state-v1';
const RECONCILE_MS = 400;
let caseLoadSequence = 0;
let mountEpoch = 0;
const actionSequence = { duty: 0, penalty: 0, stress: 0 };
const activeControllers = new Set();

const COPY = {
  ru: {
    launcher: '⚖ Юр. инструменты', dialog: 'Юридические инструменты KORGAN', close: 'Закрыть',
    title: 'Юридические инструменты', subtitle: 'Расчёты выполняет код. Правовые выводы — только по проверенным источникам РК.',
    dutyTitle: 'Госпошлина', dutyHint: 'Обычный гражданский имущественный, неимущественный или смешанный иск. Льготы и специальные категории проверяются отдельно.',
    demandType: 'Тип требования', property: 'Имущественное', nonproperty: 'Неимущественное', mixed: 'Смешанное', claimant: 'Истец', individual: 'Физлицо / ИП', legalEntity: 'Юрлицо', claimAmount: 'Цена иска, ₸', nonpropertyCount: 'Неимущественных требований', dutyAction: 'Рассчитать госпошлину', dutyResult: 'Госпошлина',
    penaltyTitle: 'Неустойка по ст. 353 ГК РК', penaltyHint: 'Законная ответственность за неправомерное пользование чужими деньгами. Ставка берётся из подтверждённого справочника НБ РК.', principal: 'Основной долг, ₸', start: 'Начало просрочки', end: 'Конец периода', rateDate: 'Дата базовой ставки', rateDateHint: 'Если не указана — используется начало периода.', penaltyAction: 'Рассчитать неустойку', penaltyResult: 'Неустойка', days: 'Дней', baseRate: 'Базовая ставка', needsRate: 'Ставка требует проверки',
    stressTitle: 'Stress Test позиции', stressHint: 'KORGAN выступает как оппонент: ищет слабые места, доказательственные и процессуальные риски и проверяет правовые выводы по действующим нормам РК.', caseLabel: 'Дело', chooseCase: 'Выберите дело…', loadingCases: 'Загружаю дела…', loadCasesError: 'Не удалось загрузить дела', focus: 'На что обратить особое внимание', focusPlaceholder: 'Например: срок исковой давности, доказательство поставки, размер неустойки…', stressAction: 'Проверить позицию', checking: 'Проверяю позицию и актуальные нормы РК…', sources: 'Источники',
    officialSource: 'Открыть официальный источник', warning: 'Льготы и специальные категории должны проверяться отдельно по материалам дела.', timeout: 'Сервис не успел ответить. Повторите запрос.', unavailable: 'Сервис временно недоступен.', unauthorized: 'Сессия Telegram недействительна. Закройте и откройте KORGAN заново.', requestFailed: 'Не удалось выполнить запрос.',
  },
  kk: {
    launcher: '⚖ Заң құралдары', dialog: 'KORGAN заң құралдары', close: 'Жабу',
    title: 'Заң құралдары', subtitle: 'Есептеулер кодпен орындалады. Құқықтық қорытындылар — тек тексерілген ҚР дереккөздері бойынша.',
    dutyTitle: 'Мемлекеттік баж', dutyHint: 'Кәдімгі азаматтық мүліктік, мүліктік емес немесе аралас талап. Жеңілдіктер мен арнайы санаттар бөлек тексеріледі.',
    demandType: 'Талап түрі', property: 'Мүліктік', nonproperty: 'Мүліктік емес', mixed: 'Аралас', claimant: 'Талап қоюшы', individual: 'Жеке тұлға / ЖК', legalEntity: 'Заңды тұлға', claimAmount: 'Талап бағасы, ₸', nonpropertyCount: 'Мүліктік емес талап саны', dutyAction: 'Мемлекеттік бажды есептеу', dutyResult: 'Мемлекеттік баж',
    penaltyTitle: 'ҚР АК 353-бабы бойынша тұрақсыздық айыбы', penaltyHint: 'Бөтен ақшаны заңсыз пайдаланғаны үшін заңды жауапкершілік. Мөлшерлеме ҚР ҰБ расталған анықтамалығынан алынады.', principal: 'Негізгі қарыз, ₸', start: 'Мерзім өткізу басталған күн', end: 'Кезеңнің соңы', rateDate: 'Базалық мөлшерлеме күні', rateDateHint: 'Көрсетілмесе — кезеңнің басталған күні қолданылады.', penaltyAction: 'Тұрақсыздық айыбын есептеу', penaltyResult: 'Тұрақсыздық айыбы', days: 'Күндер', baseRate: 'Базалық мөлшерлеме', needsRate: 'Мөлшерлемені тексеру қажет',
    stressTitle: 'Позицияның Stress Test-і', stressHint: 'KORGAN қарсы тарап сияқты әрекет етеді: әлсіз тұстарды, дәлелдеу және процестік тәуекелдерді тауып, қорытындыларды қолданыстағы ҚР нормаларымен тексереді.', caseLabel: 'Іс', chooseCase: 'Істі таңдаңыз…', loadingCases: 'Істер жүктелуде…', loadCasesError: 'Істерді жүктеу мүмкін болмады', focus: 'Неге ерекше назар аудару керек', focusPlaceholder: 'Мысалы: талап қою мерзімі, жеткізу дәлелі, тұрақсыздық айыбының мөлшері…', stressAction: 'Позицияны тексеру', checking: 'Позиция және қолданыстағы ҚР нормалары тексерілуде…', sources: 'Дереккөздер',
    officialSource: 'Ресми дереккөзді ашу', warning: 'Жеңілдіктер мен арнайы санаттар іс материалдары бойынша бөлек тексерілуі тиіс.', timeout: 'Сервис уақытында жауап бермеді. Сұрауды қайталаңыз.', unavailable: 'Сервис уақытша қолжетімсіз.', unauthorized: 'Telegram сессиясы жарамсыз. KORGAN-ды жауып, қайта ашыңыз.', requestFailed: 'Сұрауды орындау мүмкін болмады.',
  },
};

function initData() {
  return String(window.Telegram?.WebApp?.initData || globalThis.window?.__KORGAN_TG_INIT_DATA__ || '');
}

export function selectedLanguage() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(APP_STATE_KEY) || '{}');
    return parsed?.language === 'kk' ? 'kk' : 'ru';
  } catch {
    return 'ru';
  }
}

const api = createApiTransport({
  baseUrl: API_BASE,
  getTelegramInitData: initData,
  timeoutMs: 30000,
});

function beginScopedRequest(kind, epoch) {
  const requestId = ++actionSequence[kind];
  const controller = new AbortController();
  activeControllers.add(controller);
  return {
    signal: controller.signal,
    isCurrent: () => epoch === mountEpoch && requestId === actionSequence[kind] && !controller.signal.aborted,
    cleanup: () => activeControllers.delete(controller),
  };
}

function abortActiveRequests() {
  for (const controller of activeControllers) controller.abort('legal-workspace-unmounted');
  activeControllers.clear();
}

function money(value, language) {
  return new Intl.NumberFormat(language === 'kk' ? 'kk-KZ' : 'ru-RU').format(Number(value || 0)) + ' ₸';
}

function messageForError(error, language) {
  const t = COPY[language];
  if (error?.code === 'KORGAN_API_TIMEOUT') return t.timeout;
  if (error?.code === 'KORGAN_API_UNAUTHORIZED') return t.unauthorized;
  if (error?.code === 'KORGAN_API_NOT_CONNECTED' || error?.code === 'KORGAN_API_NETWORK_ERROR') return t.unavailable;
  if (error?.status === 429) return language === 'kk' ? 'Тегін кеңес лимиті аяқталды.' : 'Бесплатный лимит консультаций исчерпан.';
  if (error?.status === 422) return language === 'kk' ? 'Енгізілген деректерді тексеріңіз.' : 'Проверьте введённые данные.';
  return t.requestFailed;
}

function resultBox(id, text, language, { error = false, sourceUrl = '', sourceLabel = '' } = {}) {
  const box = document.getElementById(id);
  if (!box) return;
  box.classList.toggle('error', error);
  box.classList.add('show');
  box.textContent = text;
  const safeUrl = safeHttpsUrl(sourceUrl);
  if (safeUrl) {
    const link = document.createElement('a');
    link.className = 'korgan-legal-tool-source';
    link.href = safeUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = sourceLabel || COPY[language].officialSource;
    box.appendChild(document.createElement('br'));
    box.appendChild(link);
  }
}

function singleOption(select, text) {
  const option = document.createElement('option');
  option.value = '';
  option.textContent = text;
  select.replaceChildren(option);
}

async function loadCases(select, language, epoch) {
  const requestId = ++caseLoadSequence;
  const controller = new AbortController();
  activeControllers.add(controller);
  const t = COPY[language];
  singleOption(select, t.loadingCases);
  try {
    const payload = await api('/miniapp/cases', { signal: controller.signal });
    if (epoch !== mountEpoch || requestId !== caseLoadSequence || controller.signal.aborted || !select.isConnected) return;
    const options = [];
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = t.chooseCase;
    options.push(empty);
    for (const item of payload.cases || []) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = String(item.title || item.description || item.document_type || item.id).slice(0, 80);
      options.push(option);
    }
    select.replaceChildren(...options);
  } catch (error) {
    if (epoch !== mountEpoch || requestId !== caseLoadSequence || controller.signal.aborted || !select.isConnected) return;
    singleOption(select, `${t.loadCasesError}: ${messageForError(error, language)}`);
  } finally {
    activeControllers.delete(controller);
  }
}

function html(language) {
  const t = COPY[language];
  return `
    <section class="korgan-legal-tools-sheet" role="dialog" aria-modal="true" aria-label="${t.dialog}">
      <div class="korgan-legal-tools-head">
        <div><h2>${t.title}</h2><p>${t.subtitle}</p></div>
        <button class="korgan-legal-tools-close" type="button" aria-label="${t.close}">×</button>
      </div>
      <article class="korgan-legal-tool-card">
        <h3>${t.dutyTitle}</h3><p class="hint">${t.dutyHint}</p>
        <div class="korgan-legal-tool-grid">
          <label>${t.demandType}<select id="klt-duty-mode"><option value="property">${t.property}</option><option value="nonproperty">${t.nonproperty}</option><option value="mixed">${t.mixed}</option></select></label>
          <label>${t.claimant}<select id="klt-duty-claimant"><option value="individual">${t.individual}</option><option value="legal_entity">${t.legalEntity}</option></select></label>
          <label>${t.claimAmount}<input id="klt-duty-amount" inputmode="numeric" type="number" min="0" step="1" placeholder="5000000"></label>
          <label>${t.nonpropertyCount}<input id="klt-duty-nonproperty" inputmode="numeric" type="number" min="0" max="50" step="1" value="0"></label>
        </div>
        <button id="klt-duty-submit" class="korgan-legal-tool-action" type="button">${t.dutyAction}</button><div id="klt-duty-result" class="korgan-legal-tool-result"></div>
      </article>
      <article class="korgan-legal-tool-card">
        <h3>${t.penaltyTitle}</h3><p class="hint">${t.penaltyHint}</p>
        <div class="korgan-legal-tool-grid">
          <label class="wide">${t.principal}<input id="klt-penalty-principal" inputmode="numeric" type="number" min="1" step="1" placeholder="1000000"></label>
          <label>${t.start}<input id="klt-penalty-start" type="date"></label><label>${t.end}<input id="klt-penalty-end" type="date"></label>
          <label class="wide">${t.rateDate}<input id="klt-penalty-rate-date" type="date"><span>${t.rateDateHint}</span></label>
        </div>
        <button id="klt-penalty-submit" class="korgan-legal-tool-action" type="button">${t.penaltyAction}</button><div id="klt-penalty-result" class="korgan-legal-tool-result"></div>
      </article>
      <article class="korgan-legal-tool-card">
        <h3>${t.stressTitle}</h3><p class="hint">${t.stressHint}</p>
        <div class="korgan-legal-tool-grid">
          <label class="wide">${t.caseLabel}<select id="klt-stress-case"><option value="">${t.chooseCase}</option></select></label>
          <label class="wide">${t.focus}<textarea id="klt-stress-focus" placeholder="${t.focusPlaceholder}"></textarea></label>
        </div>
        <button id="klt-stress-submit" class="korgan-legal-tool-action" type="button">${t.stressAction}</button><div id="klt-stress-result" class="korgan-legal-tool-result"></div>
      </article>
    </section>`;
}

function unmount() {
  mountEpoch += 1;
  caseLoadSequence += 1;
  for (const kind of Object.keys(actionSequence)) actionSequence[kind] += 1;
  abortActiveRequests();
  document.getElementById('korgan-legal-tools-button')?.remove();
  document.getElementById('korgan-legal-tools-backdrop')?.remove();
}

function mount(language) {
  if (document.getElementById('korgan-legal-tools-button')) return;
  const epoch = ++mountEpoch;
  const t = COPY[language];
  const button = document.createElement('button');
  button.id = 'korgan-legal-tools-button';
  button.dataset.language = language;
  button.className = 'korgan-legal-tools-button';
  button.type = 'button';
  button.textContent = t.launcher;

  const backdrop = document.createElement('div');
  backdrop.id = 'korgan-legal-tools-backdrop';
  backdrop.className = 'korgan-legal-tools-backdrop';
  backdrop.innerHTML = html(language);
  document.body.append(button, backdrop);

  const close = () => backdrop.classList.remove('open');
  button.addEventListener('click', async () => {
    backdrop.classList.add('open');
    await loadCases(document.getElementById('klt-stress-case'), language, epoch);
  });
  backdrop.querySelector('.korgan-legal-tools-close')?.addEventListener('click', close);
  backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });

  document.getElementById('klt-duty-submit')?.addEventListener('click', async event => {
    const submit = event.currentTarget;
    const scoped = beginScopedRequest('duty', epoch);
    submit.disabled = true;
    try {
      const payload = await api('/miniapp/legal-workspace/state-duty', {
        method: 'POST', signal: scoped.signal,
        body: JSON.stringify({ mode: document.getElementById('klt-duty-mode').value, claimant_type: document.getElementById('klt-duty-claimant').value, amount_kzt: Number(document.getElementById('klt-duty-amount').value || 0), nonproperty_demands: Number(document.getElementById('klt-duty-nonproperty').value || 0) }),
      });
      if (!scoped.isCurrent()) return;
      resultBox('klt-duty-result', `${t.dutyResult}: ${money(payload.amount_kzt, language)}\n${t.warning}`, language, { sourceUrl: payload.source_url, sourceLabel: payload.source || t.officialSource });
    } catch (error) {
      if (!scoped.isCurrent()) return;
      resultBox('klt-duty-result', messageForError(error, language), language, { error: true });
    } finally {
      if (scoped.isCurrent()) submit.disabled = false;
      scoped.cleanup();
    }
  });

  document.getElementById('klt-penalty-submit')?.addEventListener('click', async event => {
    const submit = event.currentTarget;
    const scoped = beginScopedRequest('penalty', epoch);
    submit.disabled = true;
    try {
      const rateDate = document.getElementById('klt-penalty-rate-date').value;
      const payload = await api('/miniapp/legal-workspace/late-penalty-353', {
        method: 'POST', signal: scoped.signal,
        body: JSON.stringify({ principal_kzt: Number(document.getElementById('klt-penalty-principal').value || 0), start_date: document.getElementById('klt-penalty-start').value, end_date: document.getElementById('klt-penalty-end').value, rate_date: rateDate || null }),
      });
      if (!scoped.isCurrent()) return;
      if (payload.status !== 'calculated') {
        resultBox('klt-penalty-result', t.needsRate, language, { error: true, sourceUrl: payload.source_url, sourceLabel: payload.source || t.officialSource });
      } else {
        resultBox('klt-penalty-result', `${t.penaltyResult}: ${money(payload.amount_kzt, language)}\n${t.days}: ${payload.days}\n${t.baseRate}: ${payload.base_rate_percent}%\n${payload.formula}`, language, { sourceUrl: payload.source_url, sourceLabel: payload.source || t.officialSource });
      }
    } catch (error) {
      if (!scoped.isCurrent()) return;
      resultBox('klt-penalty-result', messageForError(error, language), language, { error: true });
    } finally {
      if (scoped.isCurrent()) submit.disabled = false;
      scoped.cleanup();
    }
  });

  document.getElementById('klt-stress-submit')?.addEventListener('click', async event => {
    const submit = event.currentTarget;
    const scoped = beginScopedRequest('stress', epoch);
    submit.disabled = true;
    resultBox('klt-stress-result', t.checking, language);
    try {
      const payload = await api('/miniapp/legal-workspace/stress-test', {
        method: 'POST', timeoutMs: 110000, signal: scoped.signal,
        body: JSON.stringify({ case_id: document.getElementById('klt-stress-case').value, focus: document.getElementById('klt-stress-focus').value, language: selectedLanguage() }),
      });
      if (!scoped.isCurrent()) return;
      const sources = (payload.sources || []).length ? `\n\n${t.sources}:\n${payload.sources.join('\n')}` : '';
      resultBox('klt-stress-result', `${payload.answer || ''}${sources}`, language);
    } catch (error) {
      if (!scoped.isCurrent()) return;
      resultBox('klt-stress-result', messageForError(error, language), language, { error: true });
    } finally {
      if (scoped.isCurrent()) submit.disabled = false;
      scoped.cleanup();
    }
  });
}

export function reconcileLegalWorkspace() {
  const consentedShell = document.querySelector('#root .app-shell:not(.consent-shell)');
  if (!consentedShell) {
    unmount();
    return;
  }
  const language = selectedLanguage();
  const current = document.getElementById('korgan-legal-tools-button');
  if (current && current.dataset.language !== language) unmount();
  if (!document.getElementById('korgan-legal-tools-button')) mount(language);
  const button = document.getElementById('korgan-legal-tools-button');
  const chatOpen = Boolean(document.querySelector('#root .chat-shell'));
  if (button) button.hidden = chatOpen;
  if (chatOpen) document.getElementById('korgan-legal-tools-backdrop')?.classList.remove('open');
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', reconcileLegalWorkspace, { once: true });
  else reconcileLegalWorkspace();
  globalThis.setInterval?.(reconcileLegalWorkspace, RECONCILE_MS);
}
