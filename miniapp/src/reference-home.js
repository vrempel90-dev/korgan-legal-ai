function isKazakhHome() {
  const text = document.body?.innerText || '';
  return text.includes('Басты') || text.includes('Кәсіби AI-заңгер') || text.includes('AI-заңгер');
}

function getCopy() {
  if (isKazakhHome()) {
    return {
      heroTitle: 'Сіздің AI Заңгеріңіз',
      heroText: 'Қазақстан Республикасының заңнамасына негізделген ақылды құқықтық шешімдер.',
      actions: [
        ['Кеңес', 'Құқықтық талдау және жауаптар'],
        ['Құжаттар', 'Талаптар, шарттар, шағымдар'],
        ['Талдау', 'Іс материалдары және құқықтық бағалау'],
        ['Қорғау', 'Құпиялық және деректерді бақылау'],
      ],
      skillsTitle: 'AI Заңгер не істей алады',
      skills: ['ҚР заңнамасы', 'Жылдам талдау', '24/7 қолжетімді', 'Құпия'],
      cta: 'Кеңесті бастау',
      status: 'Жүйе жұмысқа дайын',
    };
  }

  return {
    heroTitle: 'Ваш AI Юрист',
    heroText: 'Умные юридические решения на основе законодательства Республики Казахстан.',
    actions: [
      ['Консультация', 'Правовой анализ и ответы'],
      ['Документы', 'Иски, договоры, претензии'],
      ['Анализ', 'Материалы дела и правовая оценка'],
      ['Защита', 'Конфиденциальность и контроль данных'],
    ],
    skillsTitle: 'Что умеет AI Юрист',
    skills: ['Право РК', 'Быстрый анализ', '24/7 доступ', 'Конфиденциально'],
    cta: 'Начать консультацию',
    status: 'Система готова к работе',
  };
}

function mountReferenceHome() {
  const home = document.querySelector('.home-page');
  if (!home) return;

  const copy = getCopy();
  const heroTitle = home.querySelector('.hero h1');
  const heroText = home.querySelector('.hero p');
  if (heroTitle && heroTitle.textContent !== copy.heroTitle) heroTitle.textContent = copy.heroTitle;
  if (heroText && heroText.textContent !== copy.heroText) heroText.textContent = copy.heroText;

  const cards = [...home.querySelectorAll('.action-grid > .action-card:not(.personal-lawyer-card)')].slice(0, 4);
  cards.forEach((card, index) => {
    const item = copy.actions[index];
    if (!item) return;
    const title = card.querySelector('h2');
    const description = card.querySelector('p');
    if (title && title.textContent !== item[0]) title.textContent = item[0];
    if (description && description.textContent !== item[1]) description.textContent = item[1];
  });

  let panel = home.querySelector('[data-reference-capabilities="true"]');
  if (!panel) {
    panel = document.createElement('section');
    panel.className = 'reference-capabilities';
    panel.dataset.referenceCapabilities = 'true';
    const grid = home.querySelector('.action-grid');
    if (grid) grid.insertAdjacentElement('afterend', panel);
  }
  if (panel) {
    panel.innerHTML = `
      <h3>${copy.skillsTitle}</h3>
      <div class="reference-capability-grid">
        ${copy.skills.map((skill, i) => `<div class="reference-capability"><span class="reference-capability-icon">${['⚖','⌁','◴','✓'][i]}</span><span>${skill}</span></div>`).join('')}
      </div>
    `;
  }

  let cta = home.querySelector('[data-reference-cta="true"]');
  if (!cta) {
    cta = document.createElement('button');
    cta.type = 'button';
    cta.className = 'reference-consult-cta';
    cta.dataset.referenceCta = 'true';
    cta.addEventListener('click', () => {
      try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light'); } catch {}
      const consultationCard = home.querySelector('.action-grid > .action-card:not(.personal-lawyer-card)');
      consultationCard?.click();
    });
    panel?.insertAdjacentElement('afterend', cta);
  }
  if (cta) cta.innerHTML = `<strong>${copy.cta}</strong><small>${copy.status}</small>`;
}

let scheduled = false;
function scheduleMount() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    mountReferenceHome();
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scheduleMount, { once: true });
else scheduleMount();

const observer = new MutationObserver(scheduleMount);
observer.observe(document.documentElement, { childList: true, subtree: true });
