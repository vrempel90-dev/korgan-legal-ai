const STORAGE_KEY = 'korgan_document_consultation';

function clean(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

export function documentConsultationLabel(title, language = 'ru') {
  const name = clean(title) || (language === 'kk' ? 'жасалған құжат' : 'сгенерированный документ');
  return language === 'kk'
    ? `Осы құжат бойынша кеңес: ${name}`
    : `Консультация по документу: ${name}`;
}

function languageForButton(text) {
  return clean(text).includes('Іс бойынша') ? 'kk' : 'ru';
}

function replaceButtonText(button, label) {
  if (clean(button.textContent) === label) return;
  const textNodes = Array.from(button.childNodes).filter(node => node.nodeType === Node.TEXT_NODE);
  if (textNodes.length) {
    textNodes[0].textContent = ` ${label}`;
    for (const node of textNodes.slice(1)) node.textContent = '';
    return;
  }
  button.append(document.createTextNode(` ${label}`));
}

function isReadyDocumentPage(root) {
  return Array.from(root.querySelectorAll('button')).some(button => {
    const text = clean(button.textContent);
    return text.includes('Скачать готовый DOCX') || text.includes('Дайын DOCX жүктеу');
  });
}

function storedScope() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}');
    return {
      title: clean(parsed.title),
      language: parsed.language === 'kk' ? 'kk' : 'ru',
    };
  } catch {
    return { title: '', language: 'ru' };
  }
}

export function applyDocumentConsultationUi(root = document.getElementById('root')) {
  if (!root) return;

  const casePage = root.querySelector('main.page');
  if (casePage && isReadyDocumentPage(casePage)) {
    const title = clean(casePage.querySelector('.analysis-card h2')?.textContent);
    for (const button of casePage.querySelectorAll('button')) {
      const current = clean(button.textContent);
      if (current !== 'Консультация по делу' && current !== 'Іс бойынша кеңес') continue;
      const language = languageForButton(current);
      const label = documentConsultationLabel(title, language);
      replaceButtonText(button, label);
      button.dataset.documentConsultation = 'true';
      button.dataset.documentTitle = title;
      button.dataset.documentLanguage = language;
      button.setAttribute('aria-label', label);
    }
  }

  const chat = root.querySelector('.chat-shell');
  if (chat) {
    const scope = storedScope();
    if (!scope.title) return;
    const header = chat.querySelector('.subbar strong');
    const input = chat.querySelector('.composer input');
    const label = documentConsultationLabel(scope.title, scope.language);
    const placeholder = scope.language === 'kk'
      ? `«${scope.title}» құжаты бойынша сұрақ…`
      : `Вопрос по документу «${scope.title}»…`;
    if (header && clean(header.textContent) !== label) header.textContent = label;
    if (input && !input.disabled && input.placeholder !== placeholder) input.placeholder = placeholder;
  }
}

function rememberClickedDocument(event) {
  const button = event.target?.closest?.('button[data-document-consultation="true"]');
  if (!button) return;
  const title = clean(button.dataset.documentTitle);
  const language = button.dataset.documentLanguage === 'kk' ? 'kk' : 'ru';
  if (title) sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ title, language }));
}

let applyQueued = false;
function scheduleApply() {
  if (applyQueued) return;
  applyQueued = true;
  queueMicrotask(() => {
    applyQueued = false;
    applyDocumentConsultationUi();
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('click', rememberClickedDocument, true);
  document.addEventListener('click', scheduleApply, true);

  const root = document.getElementById('root');
  if (root) {
    const observer = new MutationObserver(() => scheduleApply());
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    applyDocumentConsultationUi(root);
  }
}
