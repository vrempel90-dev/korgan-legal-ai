(() => {
  'use strict';

  let autoStartApprovedDocument = false;
  const originalFetch = window.fetch.bind(window);

  const paymentUrl = value => {
    try {
      const raw = typeof value === 'string' ? value : value?.url || '';
      return String(raw);
    } catch {
      return '';
    }
  };

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = paymentUrl(args[0]);
    if (url.includes('/miniapp/documents/payments/') && response.ok) {
      try {
        const payload = await response.clone().json();
        if (payload?.payment?.status === 'approved') {
          autoStartApprovedDocument = true;
          queueMicrotask(scheduleUiSync);
        }
      } catch {}
    }
    return response;
  };

  const replacements = new Map([
    ['Ручное подтверждение', 'Автоматическая AI-проверка'],
    ['Чек прошёл предварительную проверку. Ожидается ручная сверка по истории Kaspi Pay.', 'KORGAN AI проверяет чек автоматически.'],
    ['AI не признаёт банковский факт окончательно — администратор сверяет реальный платёж.', 'KORGAN AI проверяет получателя, сумму, время платежа и номер операции.'],
    ['Юридический анализ и генерация Word ещё не начались. Оплатите документ, загрузите чек и дождитесь ручной сверки платежа администратором.', 'Юридический анализ и генерация Word начнутся после оплаты. Оплатите через Kaspi и загрузите полный чек — KORGAN AI проверит его автоматически.'],
    ['Ручная проверка', 'AI-проверка'],
    ['Қолмен растау', 'AI арқылы автоматты тексеру'],
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
      return text.includes('Подготовить оплаченный документ') || text.includes('Төленген құжатты дайындау');
    });
    if (!target) return;
    autoStartApprovedDocument = false;
    target.click();
  };

  let scheduled = false;
  function scheduleUiSync() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      syncText();
      maybeAutoStart();
    });
  }

  const style = document.createElement('style');
  style.textContent = '.manual-card,.admin-entry{display:none!important}';
  document.head.appendChild(style);

  const observer = new MutationObserver(scheduleUiSync);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  scheduleUiSync();
})();
