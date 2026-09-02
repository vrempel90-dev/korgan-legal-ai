export function clampProgress(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(numeric, 100));
}

export function stageIndexForProgress(value) {
  const progress = clampProgress(value);
  if (progress >= 100) return 4;
  if (progress >= 90) return 3;
  if (progress >= 80) return 2;
  if (progress >= 20) return 1;
  return 0;
}

export function timelineSignature({ language = 'ru', progress = 0, failed = false } = {}) {
  return `${language}|${clampProgress(progress)}|${failed ? 'failed' : 'running'}`;
}

export function isTimelineOwnedMutation(mutation, root) {
  if (!mutation || !root) return false;
  if (mutation.target === root || root.contains?.(mutation.target)) return true;

  const nodes = [
    ...Array.from(mutation.addedNodes || []),
    ...Array.from(mutation.removedNodes || []),
  ];
  return nodes.length > 0 && nodes.every(node => node === root || root.contains?.(node));
}
