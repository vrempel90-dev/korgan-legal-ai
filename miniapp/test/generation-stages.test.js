import assert from 'node:assert/strict';
import test from 'node:test';

import { STAGE_ORDER, generationSteps } from '../src/generationStages.js';

test('шаги идут в том же порядке, что и стадии бэкенда', () => {
  assert.deepEqual(STAGE_ORDER, [
    'starting',
    'legal_research',
    'drafting',
    'legal_qa',
    'document_render',
    'delivery',
  ]);
});

test('пройденным шаг становится только после сообщения о следующей стадии', () => {
  const steps = generationSteps({ stage: 'drafting', status: 'running' });
  assert.deepEqual(steps.map((item) => item.state), [
    'done', 'done', 'active', 'pending', 'pending', 'pending',
  ]);
});

test('до первой стадии ни один шаг не отмечен пройденным', () => {
  const steps = generationSteps({ stage: 'queued', status: 'queued' });
  assert.deepEqual(new Set(steps.map((item) => item.state)), new Set(['pending']));
});

test('успешная задача закрывает весь список', () => {
  const steps = generationSteps({ stage: 'completed', status: 'succeeded' });
  assert.deepEqual(new Set(steps.map((item) => item.state)), new Set(['done']));
});

test('сбой отмечает стадию, на которой работа оборвалась, и не стирает пройденное', () => {
  const steps = generationSteps({ stage: 'legal_research', status: 'failed' });
  assert.deepEqual(steps.map((item) => item.state), [
    'done', 'failed', 'pending', 'pending', 'pending', 'pending',
  ]);
});

test('неизвестная стадия не двигает список вперёд', () => {
  const steps = generationSteps({ stage: 'interrupted', status: 'failed' });
  assert.deepEqual(new Set(steps.map((item) => item.state)), new Set(['pending']));
});

test('казахский список переведён целиком', () => {
  const steps = generationSteps({ stage: 'starting', status: 'running' }, 'kk');
  assert.ok(steps.every((item) => item.label && item.label !== item.id));
});
