const AMBIGUOUS_START_ERRORS = new Set([
  'KORGAN_API_TIMEOUT',
  'KORGAN_API_NETWORK_ERROR',
]);
const ACCEPTED_JOB_STATUSES = new Set(['queued', 'running', 'succeeded', 'failed']);

function delay(milliseconds) {
  return new Promise(resolve => globalThis.setTimeout(resolve, milliseconds));
}

export function isAmbiguousGenerationStartError(error) {
  return AMBIGUOUS_START_ERRORS.has(String(error?.code || ''));
}

/**
 * A timed-out POST is ambiguous: the server may already have persisted and
 * started the paid job. Never POST again automatically. Recover the durable
 * job by case id and let the normal status polling continue from there.
 */
export async function recoverGenerationStart({
  caseId,
  error,
  fetchCaseGeneration,
  attempts = 10,
  delayMs = 700,
  sleep = delay,
}) {
  if (!isAmbiguousGenerationStartError(error)) throw error;
  if (typeof fetchCaseGeneration !== 'function') throw error;

  const id = String(caseId || '').trim();
  if (!id) throw error;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const payload = await fetchCaseGeneration(id);
      const job = payload?.job;
      const status = String(job?.status || '');
      if (job && ACCEPTED_JOB_STATUSES.has(status)) {
        return {
          payment_required: false,
          generation_started: status === 'queued' || status === 'running',
          ...payload,
          recovered_after_ambiguous_start: true,
        };
      }
    } catch {
      // The status read itself can race a deploy/network blip. The original
      // start error remains authoritative if no durable job becomes visible.
    }

    if (attempt + 1 < attempts) await sleep(delayMs);
  }

  throw error;
}
