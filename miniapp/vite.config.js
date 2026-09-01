import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Какой коммит собран в этот бандл — прямо в разметке, отдельным тегом.
//
// Живых копий фронтенда несколько, и собраны они из разных коммитов. Отличить
// их снаружи можно было только по content-hash имени файла: чтобы понять, какая
// копия новее, приходилось собирать проект локально и сравнивать хеши. Хеш при
// этом зависит и от версии сборщика, поэтому одинаковый исходник на другой
// машине давал другое имя файла — сравнение доказывало не то, что нужно.
//
// SHA подставляет Railway при сборке из GitHub. Пустое значение означает
// локальную сборку, а не сбой: тег остаётся на месте, чтобы внешняя проверка
// отличала «собрано не в Railway» от «тега нет вовсе, копия древняя».
function commitMeta() {
  const sha = (process.env.RAILWAY_GIT_COMMIT_SHA || '').trim();
  return {
    name: 'korgan-commit-meta',
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: { name: 'korgan-commit', content: sha },
          injectTo: 'head',
        },
      ];
    },
  };
}

export default defineConfig({
  plugins: [react(), commitMeta()],
  preview: {
    host: '0.0.0.0',
    allowedHosts: ['korgan-miniapp-staging-production.up.railway.app'],
  },
});
