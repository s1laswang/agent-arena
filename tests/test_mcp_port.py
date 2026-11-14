"""Keyless: `make mcp` keeps 8765 when it is free, and falls back only when it is busy."""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mcp_port.py"
_spec = importlib.util.spec_from_file_location("mcp_port", _PATH)
mcp_port = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_port)


def _bind(free):
    return lambda port: port in free


def test_default_when_8765_is_free():
    assert mcp_port.choose_port({}, _bind({8765, 8766})) == 8765


def test_fallback_when_8765_is_busy(capsys):
    assert mcp_port.choose_port({}, _bind({8766, 8767})) == 8766
    assert "8765 is busy, using 8766" in capsys.readouterr().err


def test_pinned_port_is_not_replaced():
    assert mcp_port.choose_port({"MCP_PORT": "9000"}, _bind({8765, 9000})) == 9000
    assert mcp_port.choose_port({"CANARY_PORT": "9001"}, _bind({9001})) == 9001


def test_mcp_port_wins_over_canary_port():
    env = {"MCP_PORT": "9000", "CANARY_PORT": "9001"}
    assert mcp_port.choose_port(env, _bind({9000, 9001})) == 9000


def test_pinned_busy_port_exits_without_fallback():
    with pytest.raises(mcp_port.PortBusy):
        mcp_port.choose_port({"CANARY_PORT": "8765"}, _bind(set()))


def test_main_returns_3_when_nothing_is_free(monkeypatch, capsys):
    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.delenv("CANARY_PORT", raising=False)
    monkeypatch.setattr(mcp_port, "_can_bind", lambda port: False)
    assert mcp_port.main([]) == 3
    assert "no free port" in capsys.readouterr().err
