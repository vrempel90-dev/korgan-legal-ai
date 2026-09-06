/**
 * Разбор каждого модуля до запуска тестов.
 *
 * В проекте нет TypeScript и ESLint, поэтому опечатка в модуле, который ни один
 * тест не импортирует, доживала до браузера. `node --check` разбирает файл, не
 * выполняя его: этого хватает, чтобы поймать сломанный синтаксис и незакрытую
 * скобку там, где тестов ещё нет. JSX Node не разбирает — за него отвечает
 * сборка Vite, которая падает на тех же ошибках.
 */

import { readdir } from 'node:fs/promises';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const roots = [join(here, '..', 'src'), join(here, '..', 'test')];

async function collect(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await collect(full));
    else if (extname(entry.name) === '.js') files.push(full);
  }
  return files;
}

const failures = [];
for (const root of roots) {
  for (const file of await collect(root)) {
    try {
      await run(process.execPath, ['--check', file]);
    } catch (error) {
      failures.push(`${file}\n${error.stderr || error.message}`);
    }
  }
}

if (failures.length) {
  console.error(`Синтаксис не разобран в ${failures.length} файле(ах):\n\n${failures.join('\n\n')}`);
  process.exit(1);
}
console.log('Синтаксис всех модулей разобран.');
