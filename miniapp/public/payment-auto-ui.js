(() => {
  'use strict';

  const READY_KEY = 'korgan:document-ready-after-payment:v2';
  let autoStartApprovedDocument = false;
  let openCasesAfterDocument = false;
  let scheduled = false;
  let casesNavigationStarted = false;

  const originalFetch = window.fetch.bind(window);
  const originalOpen = typeof window.open === 'function' ? window.open.bind(window) : null;

  const paymentUrl = value => {
    try {
      const raw = typeof value === 'string' ? value : value?.url || '';
      return String(raw);
    } catch {
      return '';
    }
  };

  const isKaspiUrl = value => {
    try {
      const url = new URL(String(value || ''), window.location.href);
      return url.protocol === 'https:' && (url.hostname === 'kaspi.kz' || url.hostname.endsWith('.kaspi.kz'));
    } catch {
      return false;
    }
  };

  const rememberDocumentReady = () => {
    openCasesAfterDocument = true;
    try { window.sessionStorage?.setItem(READY_KEY, '1'); } catch {}
  };

  const restoreDocumentReady = () => {
    try { return window.sessionStorage?.getItem(READY_KEY) === '1'; } catch { return false; }
  };

  const clearDocumentReady = () => {
    openCasesAfterDocument = false;
    try { window.sessionStorage?.removeItem(READY_KEY); } catch {}
  };

  const isGeneratedDocument = payload => Boolean(
    payload
      && payload.payment_required === false
      && payload.paid === true
      && (payload.document_base64 || payload.filename || payload.status === 'document_ready')
  );

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = paymentUrl(args[0]);
    const isDocumentPayment = url.includes('/miniapp/documents/payments/') || url.includes('/miniapp/documents/generate');

    if (isDocumentPayment && response.ok) {
      try {
        const payload = await response.clone().json();
        if (payload?.payment?.status === 'approved') {
          autoStartApprovedDocument = true;
        }
        if (isGeneratedDocument(payload)) {
          autoStartApprovedDocument = false;
          rememberDocumentReady();
        }
        queueMicrotask(scheduleUiSync);
      } catch {}
    }
    return response;
  };

  // Telegram WebView opens Kaspi links more reliably through WebApp.openLink.
  if (originalOpen) {
    window.open = (url, ...rest) => {
      if (isKaspiUrl(url)) {
        try {
          const tg = window.Telegram?.WebApp;
          if (typeof tg?.openLink === 'function') {
            tg.openLink(String(url));
            return null;
          }
        } catch {}
      }
      return originalOpen(url, ...rest);
    };
  }

  const replacements = new Map([
    ['Загрузить чек', 'Я оплатил'],
    ['Чекті жүктеу', 'Төледім'],
    ['Проверяю чек…', 'Проверяю оплату…'],
    ['Чек тексерілуде…', 'Төлем тексерілуде…'],
    ['Ручное подтверждение', 'Автоматическая проверка Kaspi ОФД'],
    ['Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', 'Проверяем тот же фискальный чек через Kaspi ОФД. Повторно платить не нужно.'],
    ['AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.', 'KORGAN проверяет сумму, получателя, время и уникальность фискального чека через Kaspi ОФД. AI не принимает решение о факте оплаты.'],
    ['Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.', 'Оплатите документ через Kaspi, затем нажмите «Я оплатил» и выберите электронный чек. После проверки KORGAN сразу подготовит документ и сохранит его в «Мои дела».'],
    ['Теперь можно запустить юридический анализ и генерацию Word. Новая оплата не требуется.', 'Оплата подтверждена. Документ запускается автоматически; повторная оплата не требуется.'],
    ['Подготовить оплаченный документ', 'Повторить подготовку без оплаты'],
    ['KORGAN PREPAY', 'KORGAN PAYMENT'],
    ['Ручная проверка', 'Проверка Kaspi ОФД'],
    ['Қолмен растау', 'Kaspi ОФД автоматты тексеруі'],
    ['AI арқылы автоматты тексеру', 'Kaspi ОФД автоматты тексеруі'],
    ['Құқықтық талдау мен Word генерациясы әлі басталған жоқ. Құжат үшін төлеңіз, чекті жүктеп, әкімшінің Kaspi Pay бойынша қолмен тексеруін күтіңіз.', 'Kaspi арқылы құжат үшін төлеңіз, содан кейін «Төледім» батырмасын басып, электрондық чекті таңдаңыз. Тексеруден кейін құжат бірден дайындалып, «Менің істерім» бөлімінде сақталады.'],
  ]);

  const syncText = () => {
    const root = document.body;
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const original = node.nodeValue || '';
      let next = original;
      for (const [from, to] of replacements) next = next.split(from).join(to);
      if (next !== original) node.nodeValue = next;
    }
  };

  const maybeAutoStart = () => {
    if (!autoStartApprovedDocument) return;
    const buttons = Array.from(document.querySelectorAll('button'));
    const target = buttons.find(button => {
      if (button.disabled) return false;
      const text = (button.textContent || '').trim();
      return text.includes('Повторить подготовку без оплаты')
        || text.includes('Подготовить оплаченный документ')
        || text.includes('Төленген құжатты дайындау');
    });
    if (!target) return;
    autoStartApprovedDocument = false;
    target.click();
  };

  const showSavedToast = () => {
    try {
      document.querySelector('.korgan-payment-library-toast')?.remove();
      const kk = document.documentElement.lang === 'kk';
      const toast = document.createElement('div');
      toast.className = 'korgan-payment-library-toast';
      toast.textContent = kk
        ? 'Құжат дайын және «Менің істерім» бөлімінде сақталды.'
        : 'Документ готов и сохранён в «Мои дела».';
      Object.assign(toast.style, {
        position: 'fixed', left: '50%', bottom: 'calc(84px + env(safe-area-inset-bottom))',
        transform: 'translateX(-50%)', zIndex: '2147483647',
        width: 'min(calc(100% - 28px), 480px)', padding: '12px 14px', borderRadius: '14px',
        border: '1px solid rgba(78,208,160,.28)', background: 'rgba(13,29,25,.98)',
        color: '#F3F0E9', fontSize: '13px', lineHeight: '1.35', textAlign: 'center',
        boxShadow: '0 16px 42px rgba(0,0,0,.42)', pointerEvents: 'none'
      });
      document.body.appendChild(toast);
      window.setTimeout(() => toast.remove(), 4200);
    } catch {}
  };

  const maybeOpenCases = () => {
    if (casesNavigationStarted) return;
    if (!openCasesAfterDocument && !restoreDocumentReady()) return;

    const navButtons = Array.from(document.querySelectorAll('.bottom-nav button'));
    const target = navButtons.find(button => {
      if (button.disabled) return false;
      const text = (button.textContent || '').trim();
      return text === 'Дела' || text === 'Істер';
    });
    if (!target) return;

    casesNavigationStarted = true;
    clearDocumentReady();
    target.click();
    window.setTimeout(showSavedToast, 250);
  };

  function scheduleUiSync() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      syncText();
      maybeAutoStart();
      maybeOpenCases();
    });
  }

  const style = document.createElement('style');
  style.textContent = '.manual-card,.admin-entry{display:none!important}';
  document.head.appendChild(style);

  const observer = new MutationObserver(scheduleUiSync);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  scheduleUiSync();
})();
