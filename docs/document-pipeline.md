# KORGAN — конвейер юридических документов

Документ описывает **работающий** код ветки `recovery/miniapp-api-1600-sg`,
а не желаемую архитектуру. Каждое утверждение проверено на собранном
приложении; расхождения между замыслом и реальностью отмечены явно.

Railway-сервис: `korgan-miniapp-api-recovery-1600`
(проект «KORGAN Legal AI», окружение `production`).

---

## 1. Точка входа и слои приложения

Railway запускает `python -m korgan.miniapp_telegram_launcher`, который
поднимает `uvicorn korgan.miniapp_api_recovery_cors:app`.
`Procfile` в корне относится к Telegram-боту, а не к этому сервису.

Все слои `miniapp_api*` делят **один** объект FastAPI. Он создаётся в
`miniapp_api_v2`; каждый следующий слой снимает перекрываемый маршрут через
`miniapp_api_v4._drop_route` и регистрирует свой.

```
miniapp_api            импортирует strict_bot → 26 install_*() монки-патчей
  └ miniapp_api_v2     создаёт объект FastAPI, владеет HTTP-контрактом и _generate()
     └ miniapp_api_v3  подменяет core.service, запускает обновление корпуса НПА
        └ miniapp_api_v4  оплата консультаций, админ-маршруты
           └ miniapp_api_v5  оплата документов
              └ miniapp_api_ofd → ofd_upload → payment_idempotency
                 └ manual_payment_admin, telegram_delivery, document_access, qr_analytics
                    └ miniapp_api_recovery_cors  внешний слой CORS
```

Фактические владельцы маршрутов зафиксированы в
`tests/production_routes.py` и проверяются
`tests/test_production_route_ownership.py`. Утверждать владение из отдельного
слоя нельзя: два таких утверждения противоречат друг другу, и исход зависит от
порядка импортов.

## 2. Путь генерации документа

```
POST /miniapp/documents/generate            → miniapp_api_v5.generate_document
  проверка типа документа, дела и статуса оплаты
  → v5._run_approved_document               (обёрнут payment_operation_lock)
      • fingerprint дела сверяется с оплатой → 409, если материалы изменились
      • ошибка генерации → 503, ордер остаётся approved: повторная оплата НЕ нужна
  → miniapp_api_v2.generate_document        (asyncio.Lock на пару пользователь+дело)
  → v2._case_context(case)                  только факты пользователя и материалы;
                                            ответы AI не рециклятся в факты
  → v2._generate(type, context, language)   единственная точка ветвления по типам
  → v2._release_metadata(...)               quality gate
  → build_*_docx(draft)
  → store.save                              PostgreSQL, AES-256-GCM → «Мои дела»
```

## 3. Цепочка юридического сервиса

`v2.service = ClaimPipelineV2Adapter(ClaimServiceMux(PretrialResponseProductionService))`

`PretrialResponseProductionService` имеет MRO из 22 уровней: слои хотфиксов
наслаивались годами. Полный список — в
`tests/test_claim_release_entrypoint_wiring.py` и через
`PretrialResponseProductionService.__mro__`.

`miniapp_api_v3` устанавливает одну и ту же production-цепочку одновременно в
`miniapp_api_v2.service` и `miniapp_api.service`. Это необходимо потому, что
`_generate()` маршрутизирует иск через первый указатель, а `contract`,
`response`, `pretrial`, `pretrial_response` — через `legacy._method(...)` и
второй. Инвариант `v2.service is legacy.service is v3.service` зафиксирован в
`tests/test_miniapp_runtime_parity_v3.py`: все типы используют один набор
клиентов OpenAI и одну конфигурацию, а не два способных разойтись инстанса.

## 4. Четыре типа документов

| ключ | документ | схема и черновик | рендер |
|---|---|---|---|
| `claim` | Исковое заявление | `legal_types.ClaimDraft`, `pro_claim_sections` | `claim_docx.py` |
| `pretrial` | Досудебная претензия | `pretrial.PretrialDraft` | `pretrial.build_pretrial_docx` |
| `pretrial_response` | Ответ на претензию | `pretrial_response.PretrialResponseDraft` | `pretrial_response.build_pretrial_response_docx` |
| `response` | Отзыв на иск | `response_types.ResponseToClaimDraft` | `response_docx.build_response_to_claim_docx` |

### Исковое заявление

Раздел прогнозируемых возражений ответчика в судебный иск **не выводится**.
Поле `anticipated_defenses` сохранено только для совместимости со старыми
черновиками; промпт требует возвращать `[]`, экспортёр его не печатает.
Зафиксировано в `tests/test_claim_court_facing_policy.py`.

### Досудебная претензия

Раздел `calculation` обязателен при денежном требовании и печатается
отдельным озаглавленным блоком. Срок добровольного исполнения обязателен:
от него отсчитывается момент, с которого спор можно передать в суд.
Последствия неисполнения должны называть законный следующий шаг —
«мы примем меры» блокируется.

### Ответ на претензию и отзыв на иск

Обе схемы разделяют:

- `admitted_circumstances` — что доверитель действительно не оспаривает.
  **Пустое значение допустимо и не понижает оценку**: признания не создаются;
- `disputed_circumstances` — что оспаривается и на основании каких документов;
- `calculation_review` — построчный разбор расчёта оппонента;
- `settlement_offer` (только ответ на претензию) — предложение урегулирования.

Возражение об исковой давности или процессуальном нарушении принимается,
только если даты или норма названы **в самом возражении**: дата из соседнего
раздела такой довод не подтверждает.

## 5. Проверка норм права

Разрешены только официальные источники Республики Казахстан:
`adilet.zan.kz` и `zan.gov.kz`, с проверкой идентификатора документа и
маркеров акта — `korgan/legal/official_sources.py`.

```
юридический тезис
  → поиск в официальном источнике            legal/corpus_refresh.py
  → загрузка нормы с edition_date            legal/corpus.py (SQLite)
  → сверка номера статьи и текста            claim_filing_accuracy._ground_legal_basis
  → сверка пересказа с текстом нормы         provision_check.paraphrase_defects
  → проверка свежести снимка                 claim_corpus_health
  → аудит каждой ссылки в готовом тексте     citation_audit.audit_citations
  → только после этого — в документ
```

Реестр норм: `provision_corpus.ProvisionRecord` хранит `act`, `article`,
`part`, `text`, `source_url`, `verified_on`, `level` (`VERIFIED`/`REPORTED`),
`provenance`. Редакция нормы приходит из корпуса через
`corpus_bridge` (`edition_date`).

**Устаревший или неполный снимок не удаляет право из документа.**
`claim_corpus_health` переводит документ в контролируемый путь проверки:
статус понижается до `NEEDS_VERIFICATION`, добавляется замечание
`LEGAL_GROUNDING: …`, а каждая затронутая ссылка получает видимую пометку
`[ТРЕБУЕТ ПРОВЕРКИ: сверить действующую редакцию нормы на дату подачи]`.
Пометка распознаётся `claim_docx` и `document_quality`, поэтому документ не
может уйти как готовый к подаче. Когда сверять было нечего — корпус выключен,
отсутствует, повреждён или не содержит статью — в судебный текст не
выпускается ничего.

## 6. Zero invention

Никогда не изобретаются: ФИО, БИН/ИИН, адрес, номер договора, дата, сумма,
доказательство, факт оплаты, факт направления претензии.

Механические гарантии:

- `document_quality._preserve_known_identifiers` — ИИН/БИН из материалов не
  теряется и не подменяется;
- `_PLACEHOLDER_RE` — незаполненное поле `[ТРЕБУЕТ …]` блокирует готовность;
- `claim_consistency_guard`, `claim_release_invariants` — требование без
  подтверждённого основания не проходит;
- недостающий элемент расчёта возвращается как `CalculationGap`, а не как
  правдоподобное число.

## 7. Расчёты

`korgan/legal_calculation.py` приводит каждую денежную позицию к форме
`основание · база · ставка · период · дни · формула · итог`.

Арифметика живёт в детерминированных калькуляторах:

| что | где |
|---|---|
| разбор денежных сумм | `legal_calc.AMOUNT_PATTERN`, `parse_all_amounts_kzt` |
| государственная пошлина | `legal_calc.calc_gosposhlina_claim` + `korgan/data/rates.json` |
| неустойка по статье 353 ГК РК | `legal_calc.calc_late_payment_penalty` |
| договорная неустойка | `contractual_penalty.calc_contractual_penalty` |

Правила:

- всё считается `Decimal` с `ROUND_HALF_UP`; `float` не используется;
- договорная неустойка **не** подменяется расчётом по статье 353 ГК РК;
- ставки и потолки госпошлины читаются только из `rates.json`
  (физлицо 1 % / 10 000 МРП, юрлицо 3 % / 20 000 МРП, статья 665 НК РК);
- юридические услуги и судебные расходы — отдельные позиции, в цену иска не
  входят;
- при нехватке базы, ставки или периода расчёт не выполняется.

**Один канонический разбор сумм.** `universal_word_final_hardening` больше не
подменяет функции `legal_calc`, а делегирует им. Собственная копия шаблона в
этом модуле однажды потеряла группу «(два миллиона …)» и «kzt», из-за чего
цена иска в стандартной юридической форме не распознавалась и госпошлина не
считалась.

## 8. Quality gates

`miniapp_api_v2._release_metadata` проводит все пять типов документов через
`document_quality.assess_document_quality` с одним порогом.

**Боевой порог — 10.0/10** при отсутствии hard blockers. Литерал
`MIN_READY_SCORE = 8.5` в `document_quality` — это значение ДО установки
боевых слоёв; `universal_word_quality_guard` поднимает его до 10.0.
Зафиксировано в `tests/test_evaluation_suite.py`.

Что проверяется до сборки DOCX:

| аудит | реализация |
|---|---|
| идентификаторы сторон | `_preserve_known_identifiers` |
| роли сторон | `_score_claim`, `_score_response` |
| фактическая хронология | `_score_claim`, `_score_pretrial` |
| расчёт | `legal_calculation`, `_score_pretrial`, `_score_pretrial_response` |
| аудит ссылок | `citation_audit` |
| применимость нормы | `legal_basis_fit` |
| актуальность редакции | `claim_corpus_health` |
| процессуальная часть | `claim_filing_accuracy`, `claim_state_duty` |
| доказательства и приложения | `_score_*` |
| просительная часть | `claim_core_release` |
| стиль и утечка reasoning | `_SERVICE_MARKERS`, `text_integrity` |
| целостность DOCX | `rendered_docx_blockers` |

Служебная терминология конвейера (`NEEDS_VERIFICATION`, `KORGAN QUALITY`,
`SENIOR_PREFLIGHT_SCORE`, `FILING_ACTION`, `LEGAL_GROUNDING`,
`KORGAN QA STATUS`, `PRELIMINARY DRAFT`) в теле документа блокирует выпуск.

Клиентский слой `client_safe_ui` дополнительно не даёт механике проверки
дойти до пользователя: он **заменяет** диалоговый шлюз `korgan/bot.py`, где
клиента спрашивали, можно ли оставить непроверенную статью. Решение о норме
принимает KORGAN или юрист. Контракт закреплён в
`tests/test_client_safe_gate_supersedes_waiver_flow.py`; модуль
`korgan/gate_instructions.py` в боевом рантайме не используется.

## 9. Режимы отказа

| ситуация | поведение |
|---|---|
| документ ниже порога | доставляется как PRELIMINARY с caption, перечисляющим, что исправить; статус `NEEDS_VERIFICATION` |
| неполное ядро иска (нет исполнимой просительной части) | понижается до PRELIMINARY, но **доставляется**: клиент после оплаты не должен остаться ни с чем — `claim_core_release_runtime.send_with_core_release_guard` |
| устаревший снимок корпуса | контролируемый путь проверки, ссылка остаётся с пометкой |
| корпус недоступен | правовое обоснование не выпускается в судебный текст |
| ошибка генерации после оплаты | HTTP 503, ордер остаётся `approved`, повторная оплата не требуется |
| материалы изменились после оплаты | HTTP 409 с предложением восстановить состав дела |
| пользователь переключился на другой документ | генерация подавляется, `STALE_DOCUMENT_SUPPRESSED` |

## 10. Тесты

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

PYTHONPATH=. OPENAI_API_KEY=test TELEGRAM_BOT_TOKEN=123:test \
  .venv/bin/python -m pytest -q
```

Ключевые наборы:

| набор | что закрывает |
|---|---|
| `test_production_money_parity.py` | денежные функции после установки боевых слоёв |
| `test_legal_calculation.py` | воспроизводимость расчёта |
| `test_pretrial_professional.py` | претензия |
| `test_adversarial_documents.py` | ответ на претензию и отзыв на иск |
| `test_evaluation_suite.py` | виды споров и негативные сценарии |
| `test_production_route_ownership.py` | владение HTTP-маршрутами, отсутствие дублей |
| `test_client_safe_gate_supersedes_waiver_flow.py` | клиент не решает судьбу статьи |

`tests/wrapper_chain.py` собирает исходники всей цепочки боевых обёрток:
`inspect.getsource()` показывает только внешний слой, а на генератор иска в
production надето до девяти слоёв.

## 11. Деплой и откат

CI: `.github/workflows/legal-document-quality-ci.yml` гоняет полный набор из
корня на PR в `recovery/miniapp-api-1600-sg`.

Railway `korgan-miniapp-api-recovery-1600` деплоит из ветки
`recovery/miniapp-api-1600-sg`. preDeploy выполняет три набора по отдельности:
`test_miniapp_document_access`, `test_miniapp_api_smoke`,
`test_miniapp_business_parity_v4`. Healthcheck — `/health`.

Проверка после деплоя:

```bash
curl -s https://korgan-miniapp-api-recovery-1600-production.up.railway.app/health
curl -s https://korgan-miniapp-api-recovery-1600-production.up.railway.app/miniapp/parity
```

`/health` обязан вернуть `"storage": "postgres"`: состояние «Моих дел» не
должно жить в памяти процесса.

Откат: Railway → сервис → Deployments → предыдущий успешный деплой →
Redeploy. Схема БД в этой работе не менялась, поэтому откат кода достаточен.

## 12. Диагностика

| симптом | куда смотреть |
|---|---|
| госпошлина не рассчитана | `legal_calc.gosposhlina_line`; проверить, что цена иска распознаётся `parse_amount_kzt` |
| иск всегда PRELIMINARY | `assess_document_quality(...).hard_blockers` — там причина списком |
| исчезло правовое обоснование | логи `LEGAL_GROUNDING`; корпус недоступен или не содержит статью |
| документ не доставлен | логи `STALE_DOCUMENT_SUPPRESSED` или `PRODUCTION_CLAIM_CORE_PRELIMINARY` |
| маршрут ведёт не туда | `tests/production_routes.owner(path, method)` |
| правка модуля не действует | вероятен монки-патч поверх: `grep -rn "<имя_функции> *=" korgan/` |

Последнее — самый частый источник потерянного времени в этом репозитории.
Перед правкой любой функции стоит проверить, не заменена ли она в
`strict_bot.py` или в `korgan/__init__.py`.
