// UX v2 smoke assertions for static entrypoint wiring.
// Run with: node miniapp/ux-smoke.mjs

import fs from 'node:fs';
import path from 'node:path';

const root = path.dirname(new URL(import.meta.url).pathname);
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'src', 'ux-v2.css'), 'utf8');
const access = fs.readFileSync(path.join(root, 'src', 'document-access-ui.js'), 'utf8');

const forbidden = [
  'personal-lawyer.js',
  'client-safe-ui.js',
  'payment-auto-ui.js',
  'responsive.css',
  'ux-cleanup.css',
  'nav-cleanup.css',
  'korgan-brand.css',
  'korgan-site-typography.css',
];

for (const token of forbidden) {
  if (html.includes(token)) throw new Error(`Legacy UX layer still loaded: ${token}`);
}

if (!html.includes('/src/main.jsx')) throw new Error('React entrypoint is missing');
if (!html.includes('/src/document-access-ui.js')) throw new Error('Document transport adapter is missing');
if (!html.includes('/src/ux-v2.css')) throw new Error('UX v2 stylesheet is missing');
if (!css.includes('grid-template-columns: repeat(5')) throw new Error('Stable five-item navigation rule is missing');
if (!css.includes('backdrop-filter: none !important')) throw new Error('Telegram repaint protection is missing');
if (!css.includes('.payment-card input.case-input')) throw new Error('Payment input height regression guard is missing');
if (access.includes('MutationObserver')) throw new Error('Document adapter must not mutate DOM');
if (access.includes('insertBefore(') || access.includes('createElement(\'button\')') || access.includes('createElement("button")')) {
  throw new Error('Document adapter must not inject visible controls');
}
if (!access.includes('/document/access')) throw new Error('Document access endpoint is missing');
if (!access.includes('downloadFile')) throw new Error('Telegram native download support is missing');
if (!access.includes('preview_url')) throw new Error('Preview access support is missing');

console.log('KORGAN UX v2 smoke checks passed');
