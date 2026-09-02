/**
 * Текст карточки проверки живым юристом.
 * Язык берётся только из состояния приложения.
 */

export const PERSONAL_LAWYER_URL = 'https://wa.me/77005000553';

const COPY = {
  ru: {
    kicker: 'LIVE REVIEW',
    title: 'Проверка юристом',
    description: 'Передать документ живому юристу на профессиональную проверку.',
    aria: 'Передать документ юристу на проверку в WhatsApp',
  },
  kk: {
    kicker: 'LIVE REVIEW',
    title: 'Заңгер тексеруі',
    description: 'Құжатты кәсіби тексеру үшін тірі заңгерге беру.',
    aria: 'Құжатты заңгерге WhatsApp арқылы тексеруге жіберу',
  },
};

export function personalLawyerCopy(language) {
  return COPY[language] || COPY.ru;
}
