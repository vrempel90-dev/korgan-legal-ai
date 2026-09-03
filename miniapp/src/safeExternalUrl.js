export function safeHttpsUrl(value) {
  try {
    const parsed = new URL(String(value || ''));
    return parsed.protocol === 'https:' ? parsed.href : '';
  } catch {
    return '';
  }
}
