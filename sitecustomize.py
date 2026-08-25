"""Runtime policy for GPT-5.6 latency and structured-output reliability.

Python imports ``sitecustomize`` automatically during interpreter startup when
this repository root is on ``sys.path`` (Railway runs ``python -m ...`` from
``/app``).  The patch is deliberately narrow: only OpenAI Responses calls made
by KORGAN (identified by their prompt-cache key) are adjusted.

Why this exists:
GPT-5.6 defaults to medium reasoning. KORGAN's pre-5.6 structured-output token
budgets were sized for a non-reasoning baseline, so medium reasoning could
consume the whole output allowance and return an incomplete response with an
empty ``output_text``.  That caused a slow retry and then ``JSONDecodeError``.

Policy:
- consultations and validators: reasoning=none, low verbosity;
- legal/document research and drafting: reasoning=low;
- consultations use low web-search context for minimum latency;
- retain existing token ceilings unless they are below a safe floor.
"""

from __future__ import annotations

from typing import Any


def _korgan_schema_name(kwargs: dict[str, Any]) -> str:
    key = str(kwargs.get("prompt_cache_key") or "")
    if not key.startswith("korgan:"):
        return ""
    parts = key.split(":")
    return parts[1] if len(parts) >= 2 else ""


def _apply_korgan_gpt56_policy(kwargs: dict[str, Any]) -> dict[str, Any]:
    model = str(kwargs.get("model") or "")
    schema = _korgan_schema_name(kwargs)
    if not schema or not (model == "gpt-5.6" or model.startswith("gpt-5.6-")):
        return kwargs

    out = dict(kwargs)

    latency_first = {
        "korgan_consult_research",
        "korgan_court_ready_validation",
        "korgan_contract_validation",
    }
    document_work = {
        "korgan_verified_legal_research",
        "korgan_court_ready_claim",
        "korgan_repaired_claim",
        "korgan_contract_research",
        "korgan_contract_draft",
        "korgan_contract_repair",
    }

    if schema in latency_first:
        out["reasoning"] = {"effort": "none"}
    elif schema in document_work:
        out["reasoning"] = {"effort": "low"}
    else:
        out.setdefault("reasoning", {"effort": "low"})

    text = out.get("text")
    if isinstance(text, dict):
        text = dict(text)
        text.setdefault("verbosity", "low" if schema in latency_first else "medium")
        out["text"] = text

    safe_floors = {
        "korgan_consult_research": 2400,
        "korgan_verified_legal_research": 3200,
        "korgan_court_ready_validation": 1600,
        "korgan_court_ready_claim": 5200,
        "korgan_repaired_claim": 5200,
        "korgan_contract_research": 3000,
        "korgan_contract_draft": 6500,
        "korgan_contract_validation": 1600,
        "korgan_contract_repair": 6500,
    }
    floor = safe_floors.get(schema)
    if floor is not None:
        current = int(out.get("max_output_tokens") or 0)
        if current < floor:
            out["max_output_tokens"] = floor

    if schema == "korgan_consult_research" and isinstance(out.get("tools"), list):
        tools: list[Any] = []
        for tool in out["tools"]:
            if isinstance(tool, dict) and tool.get("type") == "web_search":
                patched = dict(tool)
                patched["search_context_size"] = "low"
                tools.append(patched)
            else:
                tools.append(tool)
        out["tools"] = tools

    return out


def _install() -> None:
    try:
        from openai.resources.responses.responses import AsyncResponses, Responses
    except Exception:
        return

    if not getattr(AsyncResponses.create, "_korgan_gpt56_policy", False):
        original_async = AsyncResponses.create

        async def async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            return await original_async(self, *args, **_apply_korgan_gpt56_policy(kwargs))

        async_create._korgan_gpt56_policy = True  # type: ignore[attr-defined]
        AsyncResponses.create = async_create  # type: ignore[method-assign]

    if not getattr(Responses.create, "_korgan_gpt56_policy", False):
        original_sync = Responses.create

        def sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            return original_sync(self, *args, **_apply_korgan_gpt56_policy(kwargs))

        sync_create._korgan_gpt56_policy = True  # type: ignore[attr-defined]
        Responses.create = sync_create  # type: ignore[method-assign]


_install()
