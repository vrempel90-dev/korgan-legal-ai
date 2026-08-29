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

  const isKazakh = () => document.documentElement.lang === 'kk' || /[ӘәҒғҚқҢңӨөҰұҮүҺһІі]/.test(document.body?.innerText || '');

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

  function sanitizeAiMessages() {
    document.querySelectorAll('.bubble.ai, .bubble.ai\\ error').forEach((bubble) => {
      const raw = (bubble.textContent || '').trim();
      if (!raw || !containsInternal(raw)) return;

      const safeLines = raw
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => !containsInternal(line));

      bubble.textContent = safeLines.join('\n') || (isKazakh()
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

      textNode.textContent = isKazakh() ? ` Фото ${index + 1}` : ` Фото ${index + 1}`;
    });
  }

  function applyClientSafeUi() {
    replaceStaticCopy();
    hideInternalArchitecture();
    sanitizeAiMessages();
    friendlyMaterialNames();
  }

  const observer = new MutationObserver(() => applyClientSafeUi());

  function start() {
    applyClientSafeUi();
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
