// KORGAN Mini App UX stability smoke assertions.
// Run with: node miniapp/ux-smoke.mjs

import fs from 'node:fs';
import path from 'node:path';

const root = path.dirname(new URL(import.meta.url).pathname);
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const entry = fs.readFileSync(path.join(root, 'src', 'entry.jsx'), 'utf8');
const css = fs.readFileSync(path.join(root, 'src', 'ux-v2.css'), 'utf8');
const access = fs.readFileSync(path.join(root, 'src', 'document-access-ui.js'), 'utf8');

const forbiddenScripts = [
  'personal-lawyer.js',
  'client-safe-ui.js',
  'payment-auto-ui.js',
];
for (const token of forbiddenScripts) {
  if (html.includes(token)) throw new Error(`DOM-mutating legacy script still loaded: ${token}`);
}

const forbiddenStyles = ['responsive.css', 'nav-cleanup.css', 'personal-lawyer.css'];
for (const token of forbiddenStyles) {
  if (html.includes(token)) throw new Error(`Conflicting legacy stylesheet still loaded: ${token}`);
}

const identityStyles = [
  'professional.css',
  'korgan-site-typography.css',
  'ux-cleanup.css',
  'korgan-brand.css',
];
for (const token of identityStyles) {
  if (!html.includes(token)) throw new Error(`KORGAN identity stylesheet missing: ${token}`);
}

if (!html.includes('/src/entry.jsx')) throw new Error('Bundled app entrypoint is missing');
if (!html.includes('/src/document-access-ui.js')) throw new Error('Document transport adapter is missing');
if (!entry.includes("import './styles.css'")) throw new Error('Base stylesheet import is missing');
if (!entry.includes("import './ux-v2.css'")) throw new Error('Stability stylesheet import is missing');
if (!entry.includes("import './main.jsx'")) throw new Error('React application import is missing');
if (entry.indexOf("./ux-v2.css") > entry.indexOf("./main.jsx")) throw new Error('Stability CSS must load before React execution');

if (!css.includes('grid-template-columns: repeat(2')) throw new Error('Current 2x2 home-card layout guard is missing');
if (!css.includes('grid-template-columns: repeat(4')) throw new Error('Four-tab navigation guard is missing');
if (!css.includes('.bottom-nav button:nth-child(4)')) throw new Error('Help-tab visibility rule is missing');
if (!css.includes('backdrop-filter: none !important')) throw new Error('Telegram repaint protection is missing');
if (!css.includes('.payment-card input.case-input')) throw new Error('Payment input height regression guard is missing');
if (!css.includes('.ready-page .secondary.wide')) throw new Error('Ready-screen action stacking guard is missing');

if (access.includes('MutationObserver')) throw new Error('Document adapter must not mutate DOM');
if (access.includes('insertBefore(') || access.includes('createElement(\'button\')') || access.includes('createElement("button")')) {
  throw new Error('Document adapter must not inject visible controls');
}
if (!access.includes('/document/access')) throw new Error('Document access endpoint is missing');
if (!access.includes('downloadFile')) throw new Error('Telegram native download support is missing');
if (!access.includes('preview_url')) throw new Error('Preview access support is missing');

console.log('KORGAN current-design UX stability checks passed');
