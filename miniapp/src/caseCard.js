/**
 * Что написано на карточке дела в разделе «Мои дела».
 *
 * Заголовок
 * ---------
 * Карточка печатала `case.title` как есть, а его пишет модель. Оттуда в список
 * дел попадали «ДОГОВОР ПОСТАВКИ № <UNKNOWN>» и
 * «№ [ТРЕБУЕТ УТОЧНЕНИЯ: номер договора]»: первое — незаполненная подстановка,
 * второе — внутренняя пометка конвейера, адресованная юристу внутри документа,
 * а не название дела. Пользователь читает их как имя своего дела и видит
 * служебную кухню продукта.
 *
 * Заголовок документа при этом не переписывается: правится только то, что
 * показано в списке. Если название непригодно, карточка называет дело по типу
 * документа — это всегда верно и ничего не выдумывает.
 *
 * Подпись
 * -------
 * Подпись говорила «Файлов: 0 · Word»: число относилось к материалам дела,
 * которые загрузил пользователь, а «Word» — к готовому документу. Рядом это
 * читается как «файлов ноль, но формат Word есть». Теперь материалы и готовый
 * документ названы раздельно и каждый — только когда он действительно есть.
 */

/** Незаполненная подстановка и внутренние пометки конвейера. */
const PLACEHOLDER_RE = /<\s*unknown\s*>|\[\s*(?:ТРЕБУЕТ|НАҚТЫЛАУ|ТЕКСЕРУ)[^\]]*\]|\bnull\b|\bundefined\b/i;

/** Осиротевший номер: «ДОГОВОР ПОСТАВКИ №» после вырезанной подстановки. */
const DANGLING_NUMBER_RE = /[«"']?\s*(?:№|N|#)\s*[»"']?\s*$/;

const COPY = {
  ru: { materials: 'Материалов', document: 'Документ готов', noMaterials: 'Материалы не загружены' },
  kk: { materials: 'Материал', document: 'Құжат дайын', noMaterials: 'Материалдар жүктелмеген' },
};

const DOCUMENT_NAMES = {
  ru: {
    claim: 'Исковое заявление',
    response: 'Отзыв на иск',
    pretrial: 'Досудебная претензия',
    pretrial_response: 'Ответ на претензию',
    contract: 'Договор',
  },
  kk: {
    claim: 'Талап қою арызы',
    response: 'Талапқа пікір',
    pretrial: 'Сотқа дейінгі талап',
    pretrial_response: 'Сотқа дейінгі талапқа жауап',
    contract: 'Шарт',
  },
};

function copy(language) {
  return COPY[language === 'kk' ? 'kk' : 'ru'];
}

/** Название типа документа — запасное имя дела, которое всегда верно. */
export function documentTypeName(documentType, language = 'ru') {
  const names = DOCUMENT_NAMES[language === 'kk' ? 'kk' : 'ru'];
  return names[String(documentType || '')] || names.claim;
}

/** Годится ли строка как имя дела для человека. */
export function isDisplayableTitle(value) {
  const text = String(value || '').trim();
  if (!text) return false;
  if (PLACEHOLDER_RE.test(text)) return false;
  // «ДОГОВОР ПОСТАВКИ №» без номера — обрубок, а не название.
  return !DANGLING_NUMBER_RE.test(text);
}

/**
 * Имя дела на карточке.
 *
 * Заголовок с незаполненной подстановкой не «чинится» подстановкой другого
 * номера — его просто не существует, и выдумывать его нельзя. Дело называется
 * по типу документа.
 */
export function caseCardTitle(item, language = 'ru') {
  const title = String(item?.title || '').trim();
  if (isDisplayableTitle(title)) return title;
  return documentTypeName(item?.document_type, language);
}

/**
 * Подпись карточки: материалы дела и готовый документ — раздельно.
 *
 * «Word» появляется только когда документ действительно готов, поэтому
 * «Файлов: 0 · Word» стать нечем.
 */
export function caseCardMeta(item, language = 'ru') {
  const t = copy(language);
  const materials = Number(item?.materials_count);
  const count = Number.isFinite(materials) && materials > 0 ? materials : 0;
  const parts = [];
  if (count > 0) parts.push(`${t.materials}: ${count}`);
  if (item?.has_document) parts.push(`${t.document} · Word`);
  if (parts.length === 0) parts.push(t.noMaterials);
  return parts.join(' · ');
}
