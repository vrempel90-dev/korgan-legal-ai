const replacements = new Map([
  ['Оплатите через Kaspi и загрузите полный чек. KORGAN AI проверит получателя, сумму, время и номер операции и сразу запустит документ.', 'Оплатите через Kaspi. Затем выберите фото фискального чека с QR-кодом или вставьте открывшуюся QR-ссылку receipt.kaspi.kz. KORGAN сверит чек напрямую через Kaspi ОФД и после успешной проверки сразу запустит документ.'],
  ['Загрузить чек', 'Проверить фискальный QR'],
  ['AI проверяет чек…', 'Kaspi ОФД проверяет чек…'],
  ['Лимит бесплатных консультаций исчерпан. Оплатите одну консультацию и загрузите чек — AI проверит его и продолжит автоматически.', 'Лимит бесплатных консультаций исчерпан. Оплатите одну консультацию и выберите фото фискального QR — KORGAN проверит его через Kaspi ОФД и продолжит автоматически.'],
  ['Та же защита оплаты, что в AI-агенте: fail-closed, anti-replay, конкретный получатель и привязка ко времени текущей заявки.', 'Защита оплаты: Kaspi ОФД, точная сумма, продавец/БИН, дата и время, РНМ/ФП, способ оплаты Kaspi и anti-replay. AI не принимает решение об оплате.'],
  ['AI receipt verification', 'Kaspi ОФД · фискальный QR'],
  ['Kaspi арқылы төлеңіз және толық чекті жүктеңіз. KORGAN AI алушыны, соманы, уақытты және операция нөмірін тексеріп, құжатты бірден бастайды.', 'Kaspi арқылы төлеңіз. Содан кейін фискалдық чектегі QR бар суретті таңдаңыз немесе QR ашқан receipt.kaspi.kz сілтемесін енгізіңіз. KORGAN чекті Kaspi ОФД арқылы тікелей тексеріп, сәтті болса құжатты бірден бастайды.'],
  ['Чекті жүктеу', 'Фискалдық QR тексеру'],
  ['AI чекті тексеруде…', 'Kaspi ОФД чекті тексеруде…'],
  ['Тегін кеңес лимиті аяқталды. Бір кеңес үшін төлеңіз және чекті жүктеңіз — AI автоматты тексеріп жалғастырады.', 'Тегін кеңес лимиті аяқталды. Бір кеңес үшін төлеңіз және фискалдық QR бар суретті таңдаңыз — KORGAN оны Kaspi ОФД арқылы тексеріп, автоматты жалғастырады.'],
  ['AI-агенттегідей төлем қорғанысы: fail-closed, anti-replay, нақты алушы және ағымдағы өтінім уақытына байланыс.', 'Төлем қорғанысы: Kaspi ОФД, нақты сома, сатушы/БСН, күн/уақыт, РНМ/ФП, Kaspi төлем тәсілі және anti-replay. AI төлем туралы шешім қабылдамайды.'],
]);

function patchText(root = document.body) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    let value = node.nodeValue || '';
    let next = value;
    for (const [from, to] of replacements) {
      if (next.includes(from)) next = next.replaceAll(from, to);
    }
    if (next !== value) node.nodeValue = next;
  }

  for (const input of root.querySelectorAll?.('.payment-card input[type="file"], .payment-page input[type="file"]') || []) {
    input.setAttribute('accept', 'image/*');
    input.setAttribute('capture', 'environment');
  }
}

const observer = new MutationObserver(mutations => {
  for (const mutation of mutations) {
    for (const node of mutation.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) patchText(node);
      else if (node.nodeType === Node.TEXT_NODE && node.parentElement) patchText(node.parentElement);
    }
  }
});

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    patchText();
    observer.observe(document.body, { childList: true, subtree: true });
  }, { once: true });
} else {
  patchText();
  observer.observe(document.body, { childList: true, subtree: true });
}
