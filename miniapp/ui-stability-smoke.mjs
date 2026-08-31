import fs from 'node:fs';

const main = fs.readFileSync('src/main.jsx', 'utf8');
const api = fs.readFileSync('src/korganApi.js', 'utf8');
const access = fs.readFileSync('src/document-access-ui.js', 'utf8');
const nav = fs.readFileSync('src/nav-cleanup.css', 'utf8');
const index = fs.readFileSync('index.html', 'utf8');

const requireText = (condition, message) => {
  if (!condition) throw new Error(message);
};

requireText(main.includes('Я оплатил'), 'Payment CTA marker missing');
requireText(main.includes('openKaspiPayment'), 'Kaspi open handler missing');
requireText(api.includes('recoverPaidConsultation'), 'Paid consultation recovery missing');
requireText(api.includes('recoverApprovedDocumentPayment'), 'Approved document recovery missing');
requireText(index.includes('/src/document-access-ui.js'), 'Document access adapter is not loaded');
requireText(access.includes('/document/access'), 'Document access endpoint missing');
requireText(access.includes('downloadFile'), 'Telegram native download missing');
requireText(access.includes('preview_url'), 'Document preview access missing');
requireText(!access.includes('new MutationObserver'), 'Document adapter must not observe/mutate UI DOM');
requireText(!access.includes("createElement('button')") && !access.includes('createElement("button")'), 'Document adapter must not inject buttons');
requireText(nav.includes('repeat(4, minmax(0, 1fr))'), 'Current four-tab navigation geometry missing');
requireText(nav.includes('button:nth-child(3)') && nav.includes('display: grid !important'), 'Consultation tab must remain visible');
requireText(nav.includes('button:nth-child(4)') && nav.includes('display: none !important'), 'Help tab must remain hidden');
requireText(nav.includes('backdrop-filter: none !important'), 'Telegram fixed-layer repaint guard missing');

console.log('KORGAN current-design UI stability checks passed');
