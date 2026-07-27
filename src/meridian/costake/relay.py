"""WebSocket relay for CoStake.

A small in-process FastAPI app that fan-outs `PolygonOp` messages
between connected peers and tracks presence. Production deployments
should run this behind a real reverse proxy and persist op-logs to
disk; v0.1 keeps everything in memory.

Wire protocol — JSON messages on the WebSocket:

    {"type": "hello", "actor": "<id>", "doc": "<doc-id>"}
    {"type": "op", "doc": "<doc-id>", "op": <PolygonOp dict>}
    {"type": "presence", "doc": "<doc-id>", "cursor": <Cursor dict>}
    {"type": "snapshot_request", "doc": "<doc-id>"}
    {"type": "snapshot", "doc": "<doc-id>", "history": [<op>...]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Room:
    history: list[dict[str, Any]] = field(default_factory=list)
    peers: dict[str, Any] = field(default_factory=dict)        # actor → WebSocket
    presence: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class CoStakeRelay:
    rooms: dict[str, _Room] = field(default_factory=dict)

    def app(self):
        """Build a FastAPI app exposing the WebSocket relay."""
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect

        app = FastAPI(title="Meridian CoStake Relay", version="0.1.0")

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            actor: str | None = None
            doc_id: str | None = None
            try:
                while True:
                    text = await ws.receive_text()
                    msg = json.loads(text)
                    mtype = msg.get("type")
                    if mtype == "hello":
                        actor = str(msg["actor"])
                        doc_id = str(msg["doc"])
                        room = self.rooms.setdefault(doc_id, _Room())
                        room.peers[actor] = ws
                        # Send the full history snapshot.
                        await ws.send_text(
                            json.dumps({"type": "snapshot", "doc": doc_id, "history": list(room.history)})
                        )
                    elif mtype == "op":
                        if actor is None or doc_id is None:
                            continue
                        room = self.rooms.setdefault(doc_id, _Room())
                        room.history.append(msg["op"])
                        await self._broadcast(room, json.dumps(msg), except_actor=actor)
                    elif mtype == "presence":
                        if actor is None or doc_id is None:
                            continue
                        room = self.rooms.setdefault(doc_id, _Room())
                        room.presence[actor] = msg["cursor"]
                        await self._broadcast(room, json.dumps(msg), except_actor=actor)
                    elif mtype == "snapshot_request":
                        if doc_id is not None:
                            room = self.rooms.setdefault(doc_id, _Room())
                            await ws.send_text(
                                json.dumps({"type": "snapshot", "doc": doc_id, "history": list(room.history)})
                            )
            except WebSocketDisconnect:
                if actor and doc_id and doc_id in self.rooms:
                    self.rooms[doc_id].peers.pop(actor, None)
                    self.rooms[doc_id].presence.pop(actor, None)

        return app

    async def _broadcast(self, room: _Room, payload: str, *, except_actor: str | None) -> None:
        dead: list[str] = []
        for peer_actor, peer_ws in room.peers.items():
            if peer_actor == except_actor:
                continue
            try:
                await peer_ws.send_text(payload)
            except Exception:
                dead.append(peer_actor)
        for d in dead:
            room.peers.pop(d, None)
