"""Pulse server + tool-registry tests."""

from __future__ import annotations

import pytest

from meridian.ai.pulse.server import PulseServer
from meridian.ai.pulse.tools import build_tool_registry


def test_registry_lists_tools():
    reg = build_tool_registry()
    names = {t["name"] for t in reg.list_tools()}
    assert {"parse_deed", "run_traverse", "classify_cloud", "inverse", "forward", "health"}.issubset(names)


def test_initialize_handshake():
    s = PulseServer.default()
    resp = s.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "meridian-pulse"


def test_tools_list_returns_specs():
    s = PulseServer.default()
    resp = s.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = resp["result"]["tools"]
    assert any(t["name"] == "inverse" for t in tools)


def test_tools_call_invokes_underlying_function():
    s = PulseServer.default()
    resp = s.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "inverse", "arguments": {"p1_x": 0, "p1_y": 0, "p2_x": 3, "p2_y": 4}},
        }
    )
    assert resp["result"]["isError"] is False
    sc = resp["result"]["structuredContent"]
    assert sc["distance_m"] == pytest.approx(5.0)


def test_unknown_method_returns_error():
    s = PulseServer.default()
    resp = s.handle_request({"jsonrpc": "2.0", "id": 99, "method": "no_such_method"})
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_error():
    s = PulseServer.default()
    resp = s.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "foo", "arguments": {}}}
    )
    assert "error" in resp
