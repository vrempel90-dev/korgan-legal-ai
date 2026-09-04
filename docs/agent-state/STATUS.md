# KORGAN Agent Status

This file is the compact handoff from Codex to independent reviewers. Keep it short and replace stale content rather than appending an endless history.

Task: ARCH-002 / P0 — цена иска определяется по структурированным имущественным требованиям (FIXED, ready for independent review)
Base/head: 2836949 -> ai/agent-team-setup

Changed files:
- korgan/claim_price.py (новый): единственная точка истины для цены иска
- korgan/professional_claim_finalizer.py: `_recalculate_price` заменён на `_apply_claim_price`
- tests/test_claim_price_source_of_truth.py (новый): 20 регрессионных тестов

Root cause:
- `_recalculate_price` складывала ВСЕ денежные суммы, найденные в готовом тексте просительной
  части, без классификации требований, и записывала результат в `price_of_claim` ДО
  `_apply_state_duty`. Поэтому любая ошибка цены молча выходила как детерминированный расчёт
  пошлины со ссылкой на статью 665 НК РК.

Reproduction (на 2836949, до правки):
- моральный вред 300 000 ₸ рядом с долгом 1 200 000 ₸ → цена 1 500 000 ₸ → пошлина 15 000 ₸;
- «1 200 000 тенге × 0,1% × 78 дн. = 93 600 тенге» → цена 2 493 600 ₸ (операнды + результат);
- «… и 93 600 тенге неустойки, итого 1 293 600 тенге» → цена 2 587 200 ₸ (удвоение итога);
- цена по ст. 353 ГК РК «1 293 600 тенге (основной долг + неустойка)» перезаписывалась на 2 493 600 ₸;
- сквозной путь `FinalizedProductionClaimService`: требование с двумя суммами → пошлина 15 500 ₸
  как точный расчёт.

Implementation:
- `korgan.claim_price` классифицирует каждое требование по роли (PECUNIARY / TOTAL_ASSERTION /
  NON_PECUNIARY / PROCEDURAL / NON_MONETARY / UNDETERMINED) и суммирует только имущественные
  компоненты. Контрольный итог («итого») обязан совпасть с суммой компонентов.
- Fail closed: требование с несколькими суммами не суммируется, а признаётся неопределимым;
  `price_of_claim` обнуляется, `state_duty` = `[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]`, добавляется заметка
  с причиной. Статус остаётся NEEDS_VERIFICATION.
- Цена, уже посчитанная детерминированно (основной долг + неустойка по ст. 353 ГК РК), не
  перезаписывается, если `claim_price_amount` читает из неё ту же сумму: расшифровка сохраняется.
- Схема `ClaimDraft` не менялась, сериализация в `bot.py` не затронута.

Tests run:
- `python -m pytest -q` — 504 passed (база 2836949: 484 passed, регрессий нет).
- Фокусно: test_claim_price_source_of_truth, test_professional_claim_finalizer, test_legal_calc,
  test_deterministic_claim_fields, test_state_duty_final_hotfix, test_article_353_safe,
  test_claim_pipeline_regression — passed.

Known legal/security risk:
- LEGAL-001 (`claim_price_amount`, ложный итог по арифметическому совпадению) и ARCH-003
  (`_AMOUNT_PATTERN` склеивает «кв. 18 1 200 000») НЕ входили в задачу и остаются открытыми.
  Правка ARCH-002 сужает их поверхность в пути финалайзера: когда компоненты определены,
  `price_of_claim` перезаписывается одной суммой без посторонних чисел.
- Смешанный иск: компенсация морального вреда исключена из цены иска, но пошлина по
  неимущественному требованию отдельно НЕ рассчитывается (`calc_mixed_state_duty` не подключён) —
  выдаётся заметка проверки.
- `late_interest_hotfix._principal_amount` по-прежнему берёт ПЕРВУЮ сумму требования. Если
  требование об основном долге содержит две разные суммы, расчёт ст. 353 строится на догадке;
  после правки такой иск уходит в fail closed, а не выдаёт неверную пошлину.
- Классификаторы требований (пошлина / судебные расходы / моральный вред) — только русскоязычные;
  ограничение существовало до правки и не изменилось.

Reviewer request:
- Review only the current task/diff. Do not perform a full repository audit unless explicitly requested.
- Отдельно проверить границу fail closed в `korgan/claim_price.py::classify_request`: требование
  с несколькими суммами всегда признаётся неопределимым (REVIEW предлагал «даёт только результат»,
  выбран более строгий вариант из «Fix required» — не суммировать, а помечать на верификацию).
