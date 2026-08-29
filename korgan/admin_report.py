from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
from aiogram import Bot

from korgan.config import Settings

LOGGER = logging.getLogger(__name__)
ALMATY_TZ = ZoneInfo("Asia/Almaty")


@dataclass(frozen=True)
class AdminReportMetrics:
    free_consultations: int = 0
    consultation_users: int = 0
    paid_consultations: int = 0
    consultation_revenue_kzt: int = 0
    agent_document_payments: int = 0
    agent_document_users: int = 0
    miniapp_documents: int = 0
    miniapp_document_users: int = 0
    miniapp_document_revenue_kzt: int = 0
    database_ok: bool = True

    @property
    def document_revenue_kzt(self) -> int:
        return self.agent_document_payments * 0 + self.miniapp_document_revenue_kzt


async def _table_exists(connection: asyncpg.Connection, table: str) -> bool:
    return bool(await connection.fetchval("SELECT to_regclass($1)", f"public.{table}"))


async def collect_admin_report_metrics(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> AdminReportMetrics:
    current = (now or datetime.now(ALMATY_TZ)).astimezone(ALMATY_TZ)
    start_local = current.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = current.astimezone(timezone.utc)

    values: dict[str, Any] = {
        "free_consultations": 0,
        "consultation_users": 0,
        "paid_consultations": 0,
        "consultation_revenue_kzt": 0,
        "agent_document_payments": 0,
        "agent_document_users": 0,
        "miniapp_documents": 0,
        "miniapp_document_users": 0,
        "miniapp_document_revenue_kzt": 0,
        "database_ok": True,
    }
    if not settings.database_url.strip():
        values["database_ok"] = False
        return AdminReportMetrics(**values)

    connection: asyncpg.Connection | None = None
    try:
        connection = await asyncpg.connect(dsn=settings.database_url, command_timeout=10)

        if await _table_exists(connection, "consultation_daily_usage"):
            row = await connection.fetchrow(
                """
                SELECT COALESCE(SUM(used), 0) AS used, COUNT(*) AS users
                FROM consultation_daily_usage
                WHERE usage_date=$1
                """,
                current.date(),
            )
            if row is not None:
                values["free_consultations"] = int(row["used"] or 0)
                values["consultation_users"] = int(row["users"] or 0)

        if await _table_exists(connection, "consultation_payment_orders"):
            row = await connection.fetchrow(
                """
                SELECT COUNT(*) AS paid_count, COALESCE(SUM(amount_kzt), 0) AS revenue
                FROM consultation_payment_orders
                WHERE paid_at >= $1 AND paid_at < $2
                """,
                start_utc,
                end_utc,
            )
            if row is not None:
                values["paid_consultations"] = int(row["paid_count"] or 0)
                values["consultation_revenue_kzt"] = int(row["revenue"] or 0)

        if await _table_exists(connection, "korgan_document_receipt_replay_guard"):
            row = await connection.fetchrow(
                """
                SELECT COUNT(*) AS payments, COUNT(DISTINCT user_id) AS users
                FROM korgan_document_receipt_replay_guard
                WHERE created_at >= $1 AND created_at < $2
                """,
                start_utc,
                end_utc,
            )
            if row is not None:
                values["agent_document_payments"] = int(row["payments"] or 0)
                values["agent_document_users"] = int(row["users"] or 0)

        if await _table_exists(connection, "korgan_miniapp_document_orders"):
            row = await connection.fetchrow(
                """
                SELECT COUNT(*) AS documents,
                       COUNT(DISTINCT user_key) AS users,
                       COALESCE(SUM(amount_kzt), 0) AS revenue
                FROM korgan_miniapp_document_orders
                WHERE consumed_at >= $1 AND consumed_at < $2
                """,
                start_utc,
                end_utc,
            )
            if row is not None:
                values["miniapp_documents"] = int(row["documents"] or 0)
                values["miniapp_document_users"] = int(row["users"] or 0)
                values["miniapp_document_revenue_kzt"] = int(row["revenue"] or 0)
    except Exception:
        LOGGER.exception("ADMIN_REPORT_DATABASE_READ_FAILED")
        values["database_ok"] = False
    finally:
        if connection is not None:
            await connection.close()

    return AdminReportMetrics(**values)


def _money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₸"


def format_admin_report(
    settings: Settings,
    metrics: AdminReportMetrics,
    *,
    now: datetime | None = None,
) -> str:
    current = (now or datetime.now(ALMATY_TZ)).astimezone(ALMATY_TZ)
    agent_document_revenue = metrics.agent_document_payments * int(settings.document_price_kzt)
    document_revenue = agent_document_revenue + metrics.miniapp_document_revenue_kzt
    total_revenue = document_revenue + metrics.consultation_revenue_kzt

    lines = [
        "📊 KORGAN — ДНЕВНОЙ ОТЧЁТ",
        "",
        f"Дата: {current:%d.%m.%Y} · Алматы",
        f"Данные: с 00:00 до {current:%H:%M}",
        "",
        "💬 Консультации",
        f"• Бесплатных использовано: {metrics.free_consultations}",
        f"• Пользователей консультаций: {metrics.consultation_users}",
        f"• Оплаченных консультаций: {metrics.paid_consultations}",
        f"• Выручка консультаций: {_money(metrics.consultation_revenue_kzt)}",
        "",
        "📄 Документы",
        f"• Agent: подтверждено оплат через Kaspi ОФД: {metrics.agent_document_payments}",
        f"• Agent: плательщиков: {metrics.agent_document_users}",
        f"• Mini App: оплаченных документов завершено: {metrics.miniapp_documents}",
        f"• Mini App: клиентов: {metrics.miniapp_document_users}",
        f"• Выручка документов: {_money(document_revenue)}",
        "",
        f"💰 Подтверждённая выручка: {_money(total_revenue)}",
    ]
    if not metrics.database_ok:
        lines.extend(["", "⚠️ Часть данных Postgres недоступна; отчёт неполный."])
    return "\n".join(lines)


async def build_admin_report(settings: Settings, *, now: datetime | None = None) -> str:
    metrics = await collect_admin_report_metrics(settings, now=now)
    return format_admin_report(settings, metrics, now=now)


async def send_admin_report(bot: Bot, settings: Settings, *, now: datetime | None = None) -> bool:
    chat_id = settings.admin_report_id
    if chat_id is None:
        LOGGER.info("ADMIN_REPORT_SKIPPED recipient_not_configured")
        return False
    report = await build_admin_report(settings, now=now)
    await bot.send_message(chat_id=chat_id, text=report)
    LOGGER.info("ADMIN_REPORT_SENT chat_id=%s", chat_id)
    return True


def next_admin_report_at(now: datetime, hour: int) -> datetime:
    current = now.astimezone(ALMATY_TZ)
    safe_hour = min(23, max(0, int(hour)))
    target = current.replace(hour=safe_hour, minute=0, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


async def _admin_report_loop(bot: Bot, settings: Settings) -> None:
    while True:
        now = datetime.now(ALMATY_TZ)
        target = next_admin_report_at(now, settings.admin_report_hour_almaty)
        delay = max(1.0, (target - now).total_seconds())
        LOGGER.info("ADMIN_REPORT_NEXT at=%s", target.isoformat())
        await asyncio.sleep(delay)
        try:
            await send_admin_report(bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Reporting must never stop the legal agent or payment flow.
            LOGGER.exception("ADMIN_REPORT_SEND_FAILED")


def start_admin_report_task(bot: Bot, settings: Settings) -> asyncio.Task[None] | None:
    if settings.admin_report_id is None:
        LOGGER.info("ADMIN_REPORT_DISABLED recipient_not_configured")
        return None
    return asyncio.create_task(_admin_report_loop(bot, settings), name="korgan-admin-report")
