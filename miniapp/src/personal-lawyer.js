const PERSONAL_LAWYER_URL = 'https://wa.me/77005000553';

function isKazakhUi() {
  const text = document.body?.innerText || '';
  return text.includes('Кәсіби AI-заңгер') || text.includes('Жеке заңгеріңіз') || text.includes('Басты');
}

function copyForCurrentLanguage() {
  if (isKazakhUi()) {
    return {
      kicker: 'PERSONAL COUNSEL',
      title: 'Сіздің жеке заңгеріңіз',
      description: 'Жеке заңгермен тікелей кеңесу. Қызмет ақылы; құны мен шарттары жұмыс басталғанға дейін нақтыланады.',
      aria: 'Жеке заңгерге WhatsApp арқылы жазу',
    };
  }

  return {
    kicker: 'PERSONAL COUNSEL',
    title: 'Ваш персональный юрист',
    description: 'Прямая консультация с персональным юристом. Услуга платная; стоимость и условия уточняются до начала работы.',
    aria: 'Написать персональному юристу в WhatsApp',
  };
}

function buildCard() {
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'action-card personal-lawyer-card';
  card.dataset.personalLawyer = 'true';

  card.addEventListener('click', () => {
    try {
      window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light');
    } catch {}
    window.open(PERSONAL_LAWYER_URL, '_blank', 'noopener,noreferrer');
  });

  return card;
}

function renderCard(card) {
  const copy = copyForCurrentLanguage();
  card.setAttribute('aria-label', copy.aria);
  card.innerHTML = `
    <div class="personal-lawyer-icon" aria-hidden="true">⚖</div>
    <div class="personal-lawyer-copy">
      <span class="section-kicker">${copy.kicker}</span>
      <h2>${copy.title}</h2>
      <p>${copy.description}</p>
    </div>
    <span class="personal-lawyer-arrow" aria-hidden="true">→</span>
  `;
}

let scheduled = false;
function mountPersonalLawyerCard() {
  const grid = document.querySelector('.action-grid');
  if (!grid) return;

  let card = grid.querySelector('[data-personal-lawyer="true"]');
  if (!card) {
    card = buildCard();
    grid.appendChild(card);
  }
  renderCard(card);
}

function scheduleMount() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    mountPersonalLawyerCard();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', scheduleMount, { once: true });
} else {
  scheduleMount();
}

const observer = new MutationObserver(scheduleMount);
observer.observe(document.documentElement, { childList: true, subtree: true });
