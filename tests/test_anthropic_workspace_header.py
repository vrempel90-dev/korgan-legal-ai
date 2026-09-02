from __future__ import annotations

from korgan.ai_provider import ANTHROPIC_WORKSPACE_VARIABLE, anthropic_workspace_headers


def test_anthropic_workspace_header_is_omitted_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv(ANTHROPIC_WORKSPACE_VARIABLE, raising=False)
    assert anthropic_workspace_headers() == {}


def test_anthropic_workspace_header_is_sent_from_railway_variable(monkeypatch) -> None:
    workspace_id = "wrkspc_01KORGANPRODUCTION"
    monkeypatch.setenv(ANTHROPIC_WORKSPACE_VARIABLE, f"  {workspace_id}  ")

    assert anthropic_workspace_headers() == {
        "anthropic-workspace-id": workspace_id,
    }


def test_explicit_workspace_value_does_not_read_process_environment(monkeypatch) -> None:
    monkeypatch.setenv(ANTHROPIC_WORKSPACE_VARIABLE, "wrkspc_wrong")
    assert anthropic_workspace_headers("wrkspc_expected") == {
        "anthropic-workspace-id": "wrkspc_expected",
    }
