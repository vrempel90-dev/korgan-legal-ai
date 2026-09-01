function filled(value) {
  return typeof value === 'string' && value.trim() !== '';
}

/** Сопоставляет сохранённое сервером согласие с текущей версией условий. */
export function resolveConsent(payload, currentVersion) {
  if (!payload || typeof payload.accepted !== 'boolean' || !filled(currentVersion)) {
    throw new Error('Получен неполный статус согласия');
  }

  if (!payload.accepted) return { accepted: false, reason: 'not_accepted' };
  if (!filled(payload.terms_version)) throw new Error('Получен неполный статус согласия');
  if (payload.terms_version !== currentVersion) {
    return { accepted: false, reason: 'version_mismatch' };
  }
  return { accepted: true, reason: 'accepted' };
}
