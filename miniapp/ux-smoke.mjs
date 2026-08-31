// UX v2 smoke assertions for static entrypoint wiring.
// Run with: node miniapp/ux-smoke.mjs

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = path.dirname(new URL(import.meta.url).pathname);
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'src', 'ux-v2.css'), 'utf8');

const forbidden = [
  'document-access-ui.js',
  'personal-lawyer.js',
  'client-safe-ui.js',
  'payment-auto-ui.js',
  'responsive.css',
  'ux-cleanup.css',
  'nav-cleanup.css',
];

for (const token of forbidden) {
  if (html.includes(token)) throw new Error(`Legacy UX layer still loaded: ${token}`);
}

if (!html.includes('/src/main.jsx')) throw new Error('React entrypoint is missing');
if (!html.includes('/src/ux-v2.css')) throw new Error('UX v2 stylesheet is missing');
if (!css.includes('grid-template-columns: repeat(5')) throw new Error('Stable five-item navigation rule is missing');
if (!css.includes('backdrop-filter: none !important')) throw new Error('Telegram repaint protection is missing');
if (!css.includes('.payment-card input.case-input')) throw new Error('Payment input height regression guard is missing');

console.log('KORGAN UX v2 smoke checks passed');
