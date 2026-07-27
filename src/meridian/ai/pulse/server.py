"""Minimal MCP-style JSON-RPC server for Pulse.

Implements the subset of MCP we need today:

* ``initialize`` — capability handshake.
* ``tools/list`` — returns the tool registry.
* ``tools/call`` — invokes a tool.
* ``ping`` — keep-alive.

Transport is stdio by default (newline-delimited JSON). A future
WebSocket transport drops in the same dispatcher; the server logic is
transport-agnostic. We *do not* depend on the official MCP SDK so the
Pulse server has zero hard runtime dependencies beyond the Python
standard library.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import IO, Any

from meridian import __version__
from meridian.ai.pulse.tools import ToolRegistry, build_tool_registry


@dataclass(slots=True)
class PulseServer:
    """A simple JSON-RPC dispatcher.

    Use :meth:`handle_request` to drive the server from any transport;
    use :meth:`run_stdio` for CLI / pipe-based hosts.
    """

    registry: ToolRegistry
    server_name: str = "meridian-pulse"
    server_version: str = __version__

    @classmethod
    def default(cls) -> PulseServer:
        return cls(registry=build_tool_registry())

    # ── Transport-agnostic dispatcher ───────────────────────────────────────
    def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle one JSON-RPC request and return its response."""
        rpc_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": self.server_name, "version": self.server_version},
                    "capabilities": {"tools": {"listChanged": False}},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.registry.list_tools()}
            elif method == "tools/call":
                tool_id = params.get("name")
                arguments = params.get("arguments") or {}
                if not isinstance(tool_id, str):
                    raise ValueError("Missing 'name' in tools/call params.")
                value = self.registry.call(tool_id, arguments)
                result = {
                    "content": [{"type": "text", "text": _to_text(value)}],
                    "isError": False,
                    "structuredContent": value,
                }
            elif method == "shutdown":
                result = {}
            else:
                return _error(rpc_id, -32601, f"Method not found: {method!r}")
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        except KeyError as e:
            return _error(rpc_id, -32602, f"Unknown tool: {e}")
        except Exception as e:
            return _error(rpc_id, -32000, f"{type(e).__name__}: {e}")

    # ── Stdio transport ─────────────────────────────────────────────────────
    def run_stdio(self, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
        """Newline-delimited JSON-RPC over stdio. Returns exit code."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                stdout.write(json.dumps(_error(None, -32700, f"Parse error: {e}")) + "\n")
                stdout.flush()
                continue
            response = self.handle_request(payload)
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
            if payload.get("method") == "shutdown":
                return 0
        return 0


# ── helpers ────────────────────────────────────────────────────────────────


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
