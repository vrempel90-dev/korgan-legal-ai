import { interpretGeneration } from './generationJob.js';

/**
 * Восстанавливает экран дела только из серверных источников истины.
 *
 * Никаких локальных догадок о READY: если задача говорит succeeded, сам
 * generation endpoint обязан вернуть сохранённый документ; если дело уже
 * помечено has_document, документ перечитывается отдельным endpoint.
 */
export async function recoverCaseWorkspace(caseId, api) {
  const id = String(caseId || '').trim();
  if (!id) throw new Error('Не указано дело для восстановления');
  if (!api || typeof api.getCase !== 'function' || typeof api.caseGeneration !== 'function') {
    throw new Error('Восстановление дела не настроено');
  }

  const result = await api.getCase(id);
  const caseData = result?.case;
  if (!caseData || String(caseData.id || '') !== id) {
    throw new Error('Сервис не вернул выбранное дело');
  }

  let generationState = { status: 'idle', job: null, document: null, payment: null };
  try {
    generationState = interpretGeneration(await api.caseGeneration(id));
  } catch (error) {
    // Ошибка чтения generation state не должна стирать уже успешно загруженное
    // дело. Исключение пробрасываем только если без него мы могли бы соврать о
    // готовности документа.
    if (!caseData.has_document && caseData.status !== 'document_ready') {
      return { view: 'case', caseData, generation: null, document: null, generationError: error };
    }
    generationState = { status: 'idle', job: null, document: null, payment: null };
  }

  if (generationState.status === 'ready') {
    return {
      view: 'ready',
      caseData,
      generation: generationState.job,
      document: generationState.document,
      generationError: null,
    };
  }

  if (generationState.status === 'running' || generationState.status === 'failed') {
    return {
      view: 'generating',
      caseData,
      generation: generationState.job,
      document: null,
      generationError: null,
    };
  }

  if ((caseData.has_document || caseData.status === 'document_ready') && typeof api.getDocument === 'function') {
    const document = await api.getDocument(id);
    return { view: 'ready', caseData, generation: null, document, generationError: null };
  }

  return { view: 'case', caseData, generation: null, document: null, generationError: null };
}
