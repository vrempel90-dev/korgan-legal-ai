from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from korgan import legal_calc
from korgan import miniapp_api_v2 as core
from korgan import miniapp_api_v4 as business

router = APIRouter(prefix="/miniapp/legal-workspace", tags=["legal-workspace"])


class StateDutyRequest(BaseModel):
    mode: Literal["property", "nonproperty", "mixed"] = "property"
    claimant_type: Literal["individual", "legal_entity"] = "individual"
    amount_kzt: int = Field(default=0, ge=0, le=10**15)
    nonproperty_demands: int = Field(default=0, ge=0, le=50)


class LatePenaltyRequest(BaseModel):
    principal_kzt: int = Field(gt=0, le=10**15)
    start_date: date
    end_date: date
    rate_date: date | None = None


class StressTestRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    focus: str = Field(default="", max_length=4000)
    language: Literal["ru", "kk"] = "ru"


async def _require_identity(x_telegram_init_data: str) -> tuple[str, dict]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    return identity, state


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    freshness = legal_calc.rates_freshness()
    return {
        "jurisdiction": "KZ",
        "current_law_verification": True,
        "official_norm_source": "adilet.zan.kz",
        "documents": ["claim", "contract", "response", "pretrial", "pretrial_response"],
        "tools": ["state_duty", "late_payment_penalty_353", "position_stress_test"],
        "calculations_are_deterministic": True,
        "payment_enabled_by_workspace": False,
        "rates": freshness,
    }


@router.post("/state-duty")
async def state_duty(
    payload: StateDutyRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, object]:
    await _require_identity(x_telegram_init_data)
    individual = payload.claimant_type == "individual"

    try:
        if payload.mode == "property":
            if payload.amount_kzt <= 0:
                raise HTTPException(status_code=422, detail="Для имущественного иска укажите цену иска")
            amount = legal_calc.calc_gosposhlina_claim(payload.amount_kzt, individual)
        elif payload.mode == "nonproperty":
            demands = payload.nonproperty_demands or 1
            amount = legal_calc.calc_nonproperty_state_duty(demands=demands)
        else:
            if payload.amount_kzt <= 0:
                raise HTTPException(status_code=422, detail="Для смешанного иска укажите цену имущественного требования")
            demands = payload.nonproperty_demands or 1
            amount = legal_calc.calc_mixed_state_duty(
                payload.amount_kzt,
                individual,
                nonproperty_demands=demands,
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Актуальный МРП не подтверждён. KORGAN не будет считать пошлину по старому показателю.",
        ) from exc

    return {
        "status": "calculated",
        "amount_kzt": amount,
        "mode": payload.mode,
        "claimant_type": payload.claimant_type,
        "source": legal_calc.RATE_SOURCE_ARTICLE,
        "source_url": legal_calc.RATE_SOURCE_URL,
        "mrp": legal_calc.mrp_on(),
        "mrp_source_url": legal_calc.mrp_source_url_on(),
        "warning": (
            "Расчёт предназначен для обычного гражданского имущественного/неимущественного требования. "
            "Льготы и специальные категории должны определяться из материалов дела отдельным legal gate."
        ),
    }


@router.post("/late-penalty-353")
async def late_penalty_353(
    payload: LatePenaltyRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, object]:
    await _require_identity(x_telegram_init_data)
    rate_date = payload.rate_date or payload.start_date
    try:
        result = legal_calc.calc_late_payment_penalty(
            payload.principal_kzt,
            payload.start_date,
            payload.end_date,
            rate_date=rate_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        return {
            "status": "needs_verification",
            "amount_kzt": None,
            "reason": legal_calc.needs_rate_marker(rate_date),
            "source": legal_calc.ARTICLE_353_LABEL,
            "source_url": legal_calc.ARTICLE_353_SOURCE_URL,
        }

    return {
        "status": "calculated",
        "amount_kzt": result.amount,
        "principal_kzt": result.principal,
        "days": result.days,
        "period_from": result.start.isoformat(),
        "period_to": result.end.isoformat(),
        "rate_date": result.rate_date.isoformat(),
        "base_rate_percent": result.rate_percent,
        "formula": result.formula(),
        "source": legal_calc.ARTICLE_353_LABEL,
        "source_url": legal_calc.ARTICLE_353_SOURCE_URL,
        "rate_source_url": legal_calc.nb_rate_source_url_on(result.rate_date),
    }


@router.post("/stress-test")
async def stress_test(
    payload: StressTestRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, object]:
    identity, state = await _require_identity(x_telegram_init_data)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    context = core._case_context(case).strip()
    if not context:
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или материалы дела")

    focus = payload.focus.strip()
    question = (
        "Проведи adversarial Stress Test позиции клиента по этому делу как старший судебный юрист Республики Казахстан. "
        "Не защищай позицию автоматически: найди её слабые места, фактические пробелы, вероятные возражения оппонента, "
        "процессуальные риски, проблемы с доказательствами, сроками, подсудностью и денежными требованиями. "
        "Каждый правовой вывод подтверждай только действующей нормой РК из официального источника; если норму подтвердить "
        "нельзя — прямо укажи это и не придумывай статью. В конце дай приоритетный список действий, которые реально усиливают позицию."
    )
    if focus:
        question += f"\n\nОсобый фокус клиента: {focus}"

    quota_id = business._quota_user_id(identity)
    used: int | None = 0
    if business.settings.consultation_limit_enabled:
        used = await business.reserve_free_consultation(
            quota_id,
            business.settings.free_consultations_per_day,
        )
        if used is None:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Бесплатный лимит консультаций исчерпан. Stress Test временно недоступен; "
                    "KORGAN не включает оплату из этого инструмента."
                ),
            )

    try:
        answer, sources = await core.service.consult(
            question,
            case_context=context,
            language=payload.language,
        )
    except Exception as exc:
        if business.settings.consultation_limit_enabled and used:
            await business.release_free_consultation(quota_id)
        raise HTTPException(
            status_code=502,
            detail="Не удалось выполнить Stress Test. Лимит запроса не списан — попробуйте ещё раз.",
        ) from exc

    return {
        "status": "verified_analysis",
        "case_id": payload.case_id,
        "answer": answer,
        "sources": sources,
        "current_law_only": True,
        "jurisdiction": "KZ",
        "free_remaining": (
            max(business.settings.free_consultations_per_day - int(used or 0), 0)
            if business.settings.consultation_limit_enabled
            else None
        ),
    }
