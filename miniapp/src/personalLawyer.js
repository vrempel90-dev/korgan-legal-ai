/**
 * Текст карточки проверки юристом.
 * Язык берётся только из состояния приложения.
 */

export const PERSONAL_LAWYER_URL = 'https://wa.me/77005000553';

const COPY = {
  ru: {
    kicker: 'REVIEW',
    title: 'Проверка юристом',
    description: 'Передать документ юристу на профессиональную проверку.',
    aria: 'Передать документ юристу на проверку в WhatsApp',
  },
  kk: {
    kicker: 'REVIEW',
    title: 'Заңгер тексеруі',
    description: 'Құжатты кәсіби тексеру үшін заңгерге беру.',
    aria: 'Құжатты заңгерге WhatsApp арқылы тексеруге жіберу',
  },
};

export function personalLawyerCopy(language) {
  return COPY[language] || COPY.ru;
}
