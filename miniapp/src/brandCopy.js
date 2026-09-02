const REPLACEMENTS = new Map([
  ['KORGAN Legal AI', 'KORGAN'],
  ['KORGAN LEGAL AI', 'KORGAN'],
  ['Условия использования KORGAN Legal AI', 'Условия использования KORGAN'],
  ['KORGAN Legal AI пайдалану шарттары', 'KORGAN пайдалану шарттары'],
]);

function replaceTextNode(node) {
  const value = String(node.textContent || '');
  let next = value;
  for (const [from, to] of REPLACEMENTS) next = next.split(from).join(to);
  if (next !== value) node.textContent = next;
}

function applyBrandCopy(root = document.getElementById('root')) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    replaceTextNode(node);
    node = walker.nextNode();
  }
}

applyBrandCopy();
document.addEventListener('click', () => window.setTimeout(() => applyBrandCopy(), 0), true);
window.setInterval(() => applyBrandCopy(), 500);
