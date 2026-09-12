from __future__ import annotations

import uuid
from typing import Optional

from fastapi import WebSocket

from ..application.ports import Broadcaster


class ConnectionManager(Broadcaster):
    """Inbound adapter that also implements the outbound Broadcaster port —
    it is how the application core pushes state without knowing WebSocket
    exists. Tracks two kinds of connections per game: the two debaters
    (keyed by slot when known) and any number of audience members (keyed by
    a server-issued id), since they need different routing — audience gets
    read-only state + reactions, never the players' private WebRTC signaling.
    """

    def __init__(self) -> None:
        self._players: dict[str, dict[str, WebSocket]] = {}
        self._audience: dict[str, dict[str, WebSocket]] = {}

    # --------------------------------------------------------- debaters

    async def connect(self, game_id: str, ws: WebSocket, slot: Optional[str] = None) -> bool:
        """Accepts the socket and returns whether a peer was already in the
        room — the caller uses this to know when it's actually safe to kick
        off WebRTC signaling instead of racing the other side's connection."""
        await ws.accept()
        room = self._players.setdefault(game_id, {})
        had_peer = len(room) > 0
        key = slot or f"anon-{id(ws)}"
        room[key] = ws
        return had_peer

    def disconnect(self, game_id: str, ws: WebSocket) -> None:
        room = self._players.get(game_id)
        if room:
            for key, sock in list(room.items()):
                if sock is ws:
                    del room[key]
        self._prune(game_id)

    async def send_to_player(self, game_id: str, slot: str, payload: dict) -> None:
        ws = self._players.get(game_id, {}).get(slot)
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    async def broadcast(self, game_id: str, payload: dict) -> None:
        """Everyone in the game — both debaters and any audience — gets
        this. Used for game-state updates, which are read-only for audience."""
        for ws in list(self._players.get(game_id, {}).values()):
            try:
                await ws.send_json(payload)
            except Exception:
                pass
        for ws in list(self._audience.get(game_id, {}).values()):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def relay(self, game_id: str, sender: WebSocket, payload: dict) -> None:
        """Debater-to-debater only — used for the players' own WebRTC
        signaling, which audience must never see."""
        room = self._players.get(game_id)
        if not room:
            return
        for ws in list(room.values()):
            if ws is sender:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def relay_including_audience(self, game_id: str, sender: WebSocket, payload: dict) -> None:
        """Like relay(), but audience also gets it — used for reactions,
        which anyone watching should be able to see. The sender itself
        (whether a debater or an audience member) is always excluded — they
        already showed their own reaction locally, instantly."""
        await self.relay(game_id, sender, payload)
        for ws in list(self._audience.get(game_id, {}).values()):
            if ws is sender:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    # --------------------------------------------------------- audience

    def new_audience_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def connect_audience(self, game_id: str, audience_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._audience.setdefault(game_id, {})[audience_id] = ws

    def disconnect_audience(self, game_id: str, audience_id: str) -> None:
        room = self._audience.get(game_id)
        if room:
            room.pop(audience_id, None)
        self._prune(game_id)

    async def send_to_audience(self, game_id: str, audience_id: str, payload: dict) -> None:
        ws = self._audience.get(game_id, {}).get(audience_id)
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    # ------------------------------------------------------------- misc

    def _prune(self, game_id: str) -> None:
        if not self._players.get(game_id):
            self._players.pop(game_id, None)
        if not self._audience.get(game_id):
            self._audience.pop(game_id, None)

    def has_room(self, game_id: str) -> bool:
        return bool(self._players.get(game_id)) or bool(self._audience.get(game_id))
