(() => {
  'use strict';

  const READY_KEY = 'korgan:document-ready-after-payment:v3';
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
    try { window.sessionStorage?.setItem(READY_KEY, '1'); } catch {}
  };

  const restoreDocumentReady = () => {
    try { return window.sessionStorage?.getItem(READY_KEY) === '1'; } catch { return false; }
  };

  const clearDocumentReady = () => {
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
        if (isGeneratedDocument(payload)) rememberDocumentReady();
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

  // Keep the payment UX simple while preserving the real manual-admin state.
  // Do not hide the admin entry and do not rewrite manual review into an
  // automatic Kaspi-OFD claim.
  const replacements = new Map([
    ['Загрузить чек', 'Я оплатил'],
    ['Чекті жүктеу', 'Төледім'],
    ['Проверяю чек…', 'Отправляю чек…'],
    ['Чек тексерілуде…', 'Чек жіберілуде…'],
    ['KORGAN PREPAY', 'KORGAN PAYMENT'],
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
    if (casesNavigationStarted || !restoreDocumentReady()) return;
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
      maybeOpenCases();
    });
  }

  const observer = new MutationObserver(scheduleUiSync);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  scheduleUiSync();
})();
