import { readFileSync, writeFileSync } from 'node:fs';

const file = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(file, 'utf8');
const from = "import './styles.css';";
const to = "import './styles.css';\nimport './generation-progress.css';";
if (!source.includes("import './generation-progress.css';")) {
  if (!source.includes(from)) throw new Error('KORGAN styles import not found; refusing to patch build.');
  source = source.replace(from, to);
}
writeFileSync(file, source, 'utf8');
