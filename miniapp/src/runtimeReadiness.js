/**
 * Условия, при которых клиент соглашается работать с бэкендом.
 *
 * Проверять здесь нужно то, от чего зависит юридический результат: какой
 * движок отвечает, из каких сервисов собрана цепочка, какое целевое качество,
 * остаётся ли предварительный фолбэк и существует ли подтверждённый путь
 * проверки оплаты. Номер версии ни одного из этих свойств не выражает.
 */

function isFilled(value) {
  return typeof value === 'string' && value.trim() !== '';
}

function hasVerifiedDocumentPaymentPath(parity) {
  if (!parity?.document_payments_enabled) return true;

  // Legacy Kaspi flow: платёж подтверждает администратор.
  if (parity?.document_manual_confirmation === true) return true;

  // Production Tole flow: банковский факт подтверждает провайдер, а backend
  // дополнительно сверяет durable status, сумму и валюту. Не разрешаем
  // неизвестный automatic provider и не считаем Tole готовым без конфигурации.
  return parity?.document_payment_provider === 'tole'
    && parity?.document_manual_confirmation === false
    && parity?.automatic_payment_confirmation === true
    && parity?.tole_configured === true;
}

/** Готовность юридического рантайма; иначе — исключение. */
export function requireProfessionalRuntime(health, parity) {
  if (
    health?.status !== 'ok'
    || health?.legal_runtime !== 'strict_bot'
    || health?.word_quality_target !== '10/10'
    || health?.preliminary_fallback !== true
    || parity?.status !== 'ok'
    // Версия обязана присутствовать: так виден ответ именно parity-эндпоинта
    // KORGAN, а не случайного прокси. Совпадение с зашитым числом не требуется.
    || !isFilled(parity?.api_version)
    || parity?.service_outer !== 'ClaimPipelineV2Adapter'
    || parity?.service_claim_mux !== 'ClaimServiceMux'
    || parity?.service_stable !== 'PretrialResponseProductionService'
    || parity?.word_quality_target !== '10/10'
    || parity?.preliminary_fallback !== true
    || typeof parity?.consultation_limit_enabled !== 'boolean'
    || typeof parity?.document_payments_enabled !== 'boolean'
    || !hasVerifiedDocumentPaymentPath(parity)
  ) {
    throw new Error('KORGAN professional legal runtime is not ready');
  }
  return { ...health, parity };
}

/** Документ без метаданных выпуска показывать нельзя. */
export function requireProfessionalDocument(payload) {
  if (
    !payload
    || typeof payload.filing_ready !== 'boolean'
    || !['verified', 'preliminary'].includes(payload.release_status)
    || !payload.document_base64
  ) {
    throw new Error('KORGAN document release metadata is incomplete');
  }
  return payload;
}