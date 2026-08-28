import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

function patch(relative, from, to, label) {
  const file = path.join(root, relative);
  const source = fs.readFileSync(file, 'utf8');
  if (!source.includes(from)) throw new Error(`patch-telegram-bootstrap: missing ${label}`);
  fs.writeFileSync(file, source.replace(from, to), 'utf8');
}

patch(
  'src/korganApi.js',
  "  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;",
  "  const initData = tg?.initData || window.__KORGAN_TG_INIT_DATA__ || '';\n  if (initData) headers['X-Telegram-Init-Data'] = initData;",
  'Telegram initData fallback',
);

patch(
  'src/main.jsx',
  "  useEffect(() => { initTelegram(); setTelegramUser(getTelegramUser()); }, []);",
  "  useEffect(() => {\n    const syncTelegram = () => { initTelegram(); setTelegramUser(getTelegramUser()); };\n    syncTelegram();\n    window.addEventListener('korgan:telegram-ready', syncTelegram);\n    return () => window.removeEventListener('korgan:telegram-ready', syncTelegram);\n  }, []);",
  'Telegram SDK late-load sync',
);

console.log('KORGAN nonblocking Telegram bootstrap patch applied');
