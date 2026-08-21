from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from korgan.config import Settings
from korgan.i18n import KK
from korgan.payment import ReceiptCheck, receipt_fingerprint, receipt_hard_issues

ALMATY_TZ = ZoneInfo("Asia/Almaty")
_POOL: asyncpg.Pool | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consultation_daily_usage (
    user_id BIGINT NOT NULL,
    usage_date DATE NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
    PRIMARY KEY (user_id, usage_date)
);

CREATE TABLE IF NOT EXISTS consultation_payment_orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    question TEXT NOT NULL,
    case_context TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'ru',
    amount_kzt INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'consumed', 'cancelled')),
    receipt_hash TEXT,
    transaction_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS consultation_receipts (
    receipt_hash TEXT PRIMARY KEY,
    transaction_id TEXT,
    user_id BIGINT NOT NULL,
    order_id BIGINT NOT NULL REFERENCES consultation_payment_orders(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS consultation_receipts_transaction_unique
ON consultation_receipts(transaction_id)
WHERE transaction_id IS NOT NULL AND transaction_id <> '';

CREATE INDEX IF NOT EXISTS consultation_orders_user_status_idx
ON consultation_payment_orders(user_id, status, created_at DESC);
"""


@dataclass(frozen=True)
class ConsultationOrder:
    id: int
    user_id: int
    chat_id: int
    question: str
    case_context: str
    language: str
    amount_kzt: int
    status: str


def almaty_today(now: datetime | None = None) -> date:
    current = now.astimezone(ALMATY_TZ) if now is not None else datetime.now(ALMATY_TZ)
    return current.date()


def _require_pool() -> asyncpg.Pool:
    if _POOL is None:
        raise RuntimeError("Consultation quota store is not initialized")
    return _POOL


async def init_consultation_store(settings: Settings) -> None:
    global _POOL
    if not settings.consultation_limit_enabled:
        return
    if not settings.database_url.strip():
        raise RuntimeError("CONSULTATION_LIMIT_ENABLED requires DATABASE_URL")
    if _POOL is not None:
        return
    _POOL = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=4,
        command_timeout=15,
    )
    async with _POOL.acquire() as connection:
        await connection.execute(_SCHEMA)


async def close_consultation_store() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.close()
        _POOL = None


async def reserve_free_consultation(user_id: int, limit: int, *, day: date | None = None) -> int | None:
    if limit <= 0:
        return None
    target_day = day or almaty_today()
    row = await _require_pool().fetchrow(
        """
        INSERT INTO consultation_daily_usage(user_id, usage_date, used)
        VALUES($1, $2, 1)
        ON CONFLICT (user_id, usage_date) DO UPDATE
        SET used = consultation_daily_usage.used + 1
        WHERE consultation_daily_usage.used < $3
        RETURNING used
        """,
        user_id,
        target_day,
        limit,
    )
    return int(row["used"]) if row is not None else None


async def release_free_consultation(user_id: int, *, day: date | None = None) -> None:
    target_day = day or almaty_today()
    await _require_pool().execute(
        """
        UPDATE consultation_daily_usage
        SET used = GREATEST(used - 1, 0)
        WHERE user_id = $1 AND usage_date = $2
        """,
        user_id,
        target_day,
    )


async def consultation_usage(user_id: int, *, day: date | None = None) -> int:
    target_day = day or almaty_today()
    value = await _require_pool().fetchval(
        "SELECT used FROM consultation_daily_usage WHERE user_id = $1 AND usage_date = $2",
        user_id,
        target_day,
    )
    return int(value or 0)


async def create_consultation_order(
    *,
    user_id: int,
    chat_id: int,
    question: str,
    case_context: str,
    language: str,
    amount_kzt: int,
) -> ConsultationOrder:
    pool = _require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "UPDATE consultation_payment_orders SET status = 'cancelled' WHERE user_id = $1 AND status = 'pending'",
                user_id,
            )
            row = await connection.fetchrow(
                """
                INSERT INTO consultation_payment_orders(
                    user_id, chat_id, question, case_context, language, amount_kzt, status
                ) VALUES($1, $2, $3, $4, $5, $6, 'pending')
                RETURNING id, user_id, chat_id, question, case_context, language, amount_kzt, status
                """,
                user_id,
                chat_id,
                question,
                case_context,
                language,
                amount_kzt,
            )
    assert row is not None
    return _order_from_row(row)


async def get_consultation_order(order_id: int, user_id: int | None = None) -> ConsultationOrder | None:
    if user_id is None:
        row = await _require_pool().fetchrow(
            """
            SELECT id, user_id, chat_id, question, case_context, language, amount_kzt, status
            FROM consultation_payment_orders WHERE id = $1
            """,
            order_id,
        )
    else:
        row = await _require_pool().fetchrow(
            """
            SELECT id, user_id, chat_id, question, case_context, language, amount_kzt, status
            FROM consultation_payment_orders WHERE id = $1 AND user_id = $2
            """,
            order_id,
            user_id,
        )
    return _order_from_row(row) if row is not None else None


async def accept_consultation_receipt(
    *,
    order_id: int,
    user_id: int,
    receipt_hash: str,
    transaction_id: str,
) -> bool:
    pool = _require_pool()
    txid: str | None = transaction_id.strip() or None
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.fetchval(
                    "SELECT status FROM consultation_payment_orders WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    order_id,
                    user_id,
                )
                if status != "pending":
                    return False
                await connection.execute(
                    """
                    INSERT INTO consultation_receipts(receipt_hash, transaction_id, user_id, order_id)
                    VALUES($1, $2, $3, $4)
                    """,
                    receipt_hash,
                    txid,
                    user_id,
                    order_id,
                )
                updated = await connection.execute(
                    """
                    UPDATE consultation_payment_orders
                    SET status = 'paid', receipt_hash = $3, transaction_id = $4, paid_at = NOW()
                    WHERE id = $1 AND user_id = $2 AND status = 'pending'
                    """,
                    order_id,
                    user_id,
                    receipt_hash,
                    txid,
                )
                return updated.endswith("1")
    except asyncpg.UniqueViolationError:
        return False


async def mark_consultation_consumed(order_id: int, user_id: int) -> bool:
    updated = await _require_pool().execute(
        """
        UPDATE consultation_payment_orders
        SET status = 'consumed', consumed_at = NOW()
        WHERE id = $1 AND user_id = $2 AND status = 'paid'
        """,
        order_id,
        user_id,
    )
    return updated.endswith("1")


def _order_from_row(row: Any) -> ConsultationOrder:
    return ConsultationOrder(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        chat_id=int(row["chat_id"]),
        question=str(row["question"]),
        case_context=str(row["case_context"] or ""),
        language=str(row["language"] or "ru"),
        amount_kzt=int(row["amount_kzt"]),
        status=str(row["status"]),
    )


def _signature(settings: Settings, user_id: int, order_id: int) -> str:
    body = f"consult:{user_id}:{order_id}".encode("utf-8")
    return hmac.new(settings.telegram_bot_token.encode("utf-8"), body, hashlib.sha256).hexdigest()[:12]


def verify_consultation_signature(settings: Settings, signature: str, user_id: int, order_id: int) -> bool:
    return hmac.compare_digest(signature, _signature(settings, user_id, order_id))


def consultation_payment_text(language: str, free_limit: int, amount_kzt: int) -> str:
    amount = f"{amount_kzt:,}".replace(",", " ")
    if language == KK:
        return (
            "⚖️ Бүгінгі тегін кеңес лимиті аяқталды\n\n"
            f"Бүгін {free_limit} тегін кеңестің {free_limit}-і пайдаланылды.\n"
            f"Келесі бір кеңес — {amount} ₸.\n\n"
            "Сұрағыңыз сақталды. Kaspi арқылы төлеңіз, содан кейін «✅ Төледім» түймесін басып, толық чекті жіберіңіз.\n\n"
            "Чек AI арқылы автоматты тексеруден өткеннен кейін осы сұрақ бірден өңделеді."
        )
    return (
        "⚖️ Бесплатный лимит консультаций на сегодня исчерпан\n\n"
        f"Использовано: {free_limit} из {free_limit} бесплатных консультаций.\n"
        f"Следующая одна консультация — {amount} ₸.\n\n"
        "Ваш вопрос сохранён. Оплатите через Kaspi, затем нажмите «✅ Я оплатил» и пришлите полный чек.\n\n"
        "После успешной автоматической AI-проверки чека этот вопрос будет обработан сразу."
    )


def consultation_payment_markup(settings: Settings, user_id: int, order_id: int, language: str) -> InlineKeyboardMarkup:
    signature = _signature(settings, user_id, order_id)
    pay_text = "💳 Kaspi арқылы төлеу" if language == KK else "💳 Оплатить через Kaspi"
    paid_text = "✅ Төледім" if language == KK else "✅ Я оплатил"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pay_text, url=settings.kaspi_payment_url)],
        [InlineKeyboardButton(text=paid_text, callback_data=f"cp:proof:{order_id}:{signature}")],
    ])


def retry_markup(settings: Settings, user_id: int, order_id: int, language: str) -> InlineKeyboardMarkup:
    signature = _signature(settings, user_id, order_id)
    text = "🔁 Кеңесті қайталау" if language == KK else "🔁 Повторить консультацию"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"cp:retry:{order_id}:{signature}")]
    ])


def strict_consultation_receipt_issues(check: ReceiptCheck, expected_amount: int) -> list[str]:
    issues = list(receipt_hard_issues(check, expected_amount))
    if not check.date_time.strip():
        issues.append("на чеке не распознаны дата и время")
    if not check.merchant_or_recipient.strip():
        issues.append("на чеке не распознан получатель платежа")
    if not check.receipt_or_transaction_id.strip() and not check.fp.strip():
        issues.append("не распознан номер операции/чека или ФП")
    if check.suspicious_signals:
        issues.append("AI обнаружил признаки возможного редактирования или аномалии")
    return issues
