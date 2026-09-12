from __future__ import annotations

from fastapi import WebSocket

from ..application.ports import Broadcaster


class ConnectionManager(Broadcaster):
    """Inbound adapter that also implements the outbound Broadcaster port —
    it is how the application core pushes state without knowing WebSocket exists.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, game_id: str, ws: WebSocket) -> bool:
        """Accepts the socket and returns whether a peer was already in the
        room — the caller uses this to know when it's actually safe to kick
        off WebRTC signaling instead of racing the other side's connection."""
        await ws.accept()
        room = self._rooms.setdefault(game_id, set())
        had_peer = len(room) > 0
        room.add(ws)
        return had_peer

    def disconnect(self, game_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(game_id)
        if room and ws in room:
            room.discard(ws)
        if room is not None and not room:
            self._rooms.pop(game_id, None)

    async def broadcast(self, game_id: str, payload: dict) -> None:
        room = self._rooms.get(game_id)
        if not room:
            return
        dead = []
        for ws in room:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            room.discard(ws)

    async def relay(self, game_id: str, sender: WebSocket, payload: dict) -> None:
        """Send to every other connection in the room except the sender —
        used for WebRTC signaling, which is peer-to-peer, not a broadcast."""
        room = self._rooms.get(game_id)
        if not room:
            return
        for ws in room:
            if ws is sender:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    def has_room(self, game_id: str) -> bool:
        return bool(self._rooms.get(game_id))
