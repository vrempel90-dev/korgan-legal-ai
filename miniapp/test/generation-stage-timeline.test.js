import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  stageIndexForProgress,
  timelineSignature,
} from '../src/generationStageState.js';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'src', 'generationStageTimeline.js'), 'utf8');

test('этапы отражают только реальные backend thresholds', () => {
  assert.equal(stageIndexForProgress(0), 0);
  assert.equal(stageIndexForProgress(19), 0);
  assert.equal(stageIndexForProgress(20), 1);
  assert.equal(stageIndexForProgress(79), 1);
  assert.equal(stageIndexForProgress(80), 2);
  assert.equal(stageIndexForProgress(89), 2);
  assert.equal(stageIndexForProgress(90), 3);
  assert.equal(stageIndexForProgress(99), 3);
  assert.equal(stageIndexForProgress(100), 4);
});

test('одинаковое состояние имеет одинаковую подпись и не требует перерисовки', () => {
  assert.equal(
    timelineSignature({ language: 'ru', progress: 20, failed: false }),
    timelineSignature({ language: 'ru', progress: 20, failed: false }),
  );
  assert.notEqual(
    timelineSignature({ language: 'ru', progress: 20, failed: false }),
    timelineSignature({ language: 'ru', progress: 80, failed: false }),
  );
  assert.notEqual(
    timelineSignature({ language: 'ru', progress: 80, failed: false }),
    timelineSignature({ language: 'ru', progress: 80, failed: true }),
  );
});

test('timeline слушает только lifecycle job и не наблюдает весь документ', () => {
  assert.ok(source.includes("const LIFECYCLE_EVENT = 'korgan:generation-lifecycle'"));
  assert.ok(source.includes('window.addEventListener(LIFECYCLE_EVENT, scheduleSync)'));
  assert.ok(!source.includes('MutationObserver'), 'глобальный DOM observer для progress запрещён');
  assert.ok(!source.includes('document.documentElement'), 'progress не должен подписываться на весь документ');
  assert.ok(!source.includes('setInterval('), 'постоянный repaint-loop недопустим');
});

test('progress overlay не управляет нижней навигацией', () => {
  assert.ok(!source.includes('syncVisibleNavigation'), 'progress script не должен менять active у вкладок');
  assert.ok(!source.includes("addEventListener('pointerdown'"), 'progress script не должен перехватывать pointerdown вкладок');
  assert.ok(source.includes('root.dataset.signature === signature'), 'рендер обязан быть идемпотентным');
});
