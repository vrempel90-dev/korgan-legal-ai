(() => {
  'use strict';

  const INTERNAL_PATTERNS = [
    /вызываем(?:ый|ого)\s+инструмент/i,
    /\btool[_\s-]?(?:call|result|output)\b/i,
    /\bfunction[_\s-]?call\b/i,
    /\bsystem\s+prompt\b/i,
    /\bdeveloper\s+(?:message|instruction)\b/i,
    /\bdebug\b/i,
    /\btraceback\b/i,
    /\bKORGAN\s+QA\b/i,
    /\bNEEDS_VERIFICATION\b/i,
    /\bsource-bound\b/i,
  ];

  const TEXT_REPLACEMENTS = new Map([
    ['Профессиональный AI-юрист', 'Ваш AI Юрист'],
    ['Кәсіби AI-заңгер', 'Сіздің AI заңгеріңіз'],
    ['Production Word-документы KORGAN', 'Юридические документы в Word'],
    ['KORGAN production Word-құжаттары', 'Word форматындағы заңдық құжаттар'],
    [
      'Mini App использует отдельный API и не изменяет production Telegram‑агента.',
      'Ваши материалы защищены и используются только для работы с вашим делом.',
    ],
    [
      'Mini App бөлек API қолданады және production Telegram‑агентін өзгертпейді.',
      'Материалдарыңыз қорғалған және тек ісіңізбен жұмыс істеу үшін пайдаланылады.',
    ],
  ]);

  function storedLanguage() {
    try {
      const raw = localStorage.getItem('korgan-miniapp-state-v1');
      const state = raw ? JSON.parse(raw) : null;
      return state?.language === 'kk' ? 'kk' : 'ru';
    } catch {
      return 'ru';
    }
  }

  const isKazakh = () => document.documentElement.lang === 'kk' || storedLanguage() === 'kk';

  function containsInternal(text) {
    return INTERNAL_PATTERNS.some((pattern) => pattern.test(text));
  }

  function replaceStaticCopy() {
    document.querySelectorAll('h1, h2, p, small, span, strong').forEach((node) => {
      if (node.childElementCount) return;
      const current = (node.textContent || '').trim();
      const replacement = TEXT_REPLACEMENTS.get(current);
      if (replacement) node.textContent = replacement;
    });
  }

  function hideInternalArchitecture() {
    document.querySelectorAll('.system-card').forEach((node) => {
      node.style.display = 'none';
      node.setAttribute('aria-hidden', 'true');
    });

    document.querySelectorAll('.case-description').forEach((node) => {
      node.style.display = 'none';
      node.setAttribute('aria-hidden', 'true');
    });
  }

  function normalizeBottomDock() {
    document.querySelectorAll('.bottom-nav').forEach((nav) => {
      nav.style.setProperty('grid-template-columns', 'repeat(2, minmax(0, 1fr))', 'important');
      const buttons = Array.from(nav.children).filter((node) => node instanceof HTMLButtonElement);
      buttons.forEach((button, index) => {
        const visible = index === 0 || index === 4;
        button.style.setProperty('display', visible ? 'grid' : 'none', 'important');
        button.setAttribute('aria-hidden', visible ? 'false' : 'true');
        if (!visible) button.tabIndex = -1;
      });
    });
  }

  function keepReadyDocumentInsideCase() {
    const readyPage = document.querySelector('main.ready-page');
    if (!readyPage || readyPage.dataset.korganReturnToCase === '1') return;
    const shell = readyPage.closest('.app-shell');
    const backButton = shell?.querySelector('.subbar .icon-btn');
    if (!(backButton instanceof HTMLButtonElement)) return;

    readyPage.dataset.korganReturnToCase = '1';
    window.setTimeout(() => {
      if (readyPage.isConnected) backButton.click();
    }, 0);
  }

  function showDocumentInsideCase() {
    const kk = isKazakh();
    document.querySelectorAll('main.page').forEach((page) => {
      if (!page.querySelector('.status-card')) return;
      const buttons = Array.from(page.querySelectorAll('button.secondary.wide'));
      const download = buttons.find((button) => /скачать.*документ|скачать.*docx|дайын.*құжат|құжат.*жүктеу/i.test(button.textContent || ''));
      if (!download) return;

      if (!page.querySelector('.korgan-inline-document-ready')) {
        const note = document.createElement('div');
        note.className = 'success-note korgan-inline-document-ready';
        note.textContent = kk
          ? 'Құжат дайын және осы істе сақталды.'
          : 'Документ готов и сохранён в этом деле.';
        download.parentNode?.insertBefore(note, download);
      }

      const spans = Array.from(download.querySelectorAll('span'));
      if (spans.length) {
        spans[spans.length - 1].textContent = kk ? 'DOCX жүктеу' : 'Скачать DOCX';
      } else {
        const textNodes = Array.from(download.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE);
        if (textNodes.length) textNodes[textNodes.length - 1].textContent = kk ? ' DOCX жүктеу' : ' Скачать DOCX';
      }
    });
  }

  function sanitizeAiMessages() {
    const kk = isKazakh();
    document.querySelectorAll('.bubble.ai, .bubble.ai\\ error').forEach((bubble) => {
      const raw = (bubble.textContent || '').trim();
      if (!raw || !containsInternal(raw)) return;

      const safeLines = raw
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => !containsInternal(line));

      bubble.textContent = safeLines.join('\n') || (kk
        ? 'Құқықтық талдауды жалғастырып жатырмын…'
        : 'Продолжаю юридический анализ…');
    });
  }

  function friendlyMaterialNames() {
    document.querySelectorAll('.material-list span').forEach((row, index) => {
      const textNode = Array.from(row.childNodes).find(
        (node) => node.nodeType === Node.TEXT_NODE && (node.textContent || '').trim(),
      );
      if (!textNode) return;

      const original = (textNode.textContent || '').trim();
      const isRawPhotoName = /^(?:photo[_-])?\d+\.(?:jpe?g|png|webp)$/i.test(original);
      if (!isRawPhotoName) return;

      textNode.textContent = ` Фото ${index + 1}`;
    });
  }

  function applyClientSafeUi() {
    replaceStaticCopy();
    hideInternalArchitecture();
    normalizeBottomDock();
    keepReadyDocumentInsideCase();
    showDocumentInsideCase();
    sanitizeAiMessages();
    friendlyMaterialNames();
  }

  let applyScheduled = false;
  function scheduleApply() {
    if (applyScheduled) return;
    applyScheduled = true;
    window.requestAnimationFrame(() => {
      applyScheduled = false;
      applyClientSafeUi();
    });
  }

  const observer = new MutationObserver(scheduleApply);

  function start() {
    applyClientSafeUi();
    // Observe only the React application root and batch changes to one pass per
    // animation frame. This avoids repeated full-page work in Telegram WebView.
    const root = document.getElementById('root') || document.body;
    observer.observe(root, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();