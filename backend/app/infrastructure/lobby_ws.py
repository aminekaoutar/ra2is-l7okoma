from __future__ import annotations

from fastapi import WebSocket

from ..application.lobby_ports import LobbyNotifier


class LobbyConnectionManager(LobbyNotifier):
    """Tracks one live WebSocket per waiting lobby entry, so a match found as
    a side effect of someone else's join() can still reach this connection."""

    def __init__(self) -> None:
        self._conns: dict[str, WebSocket] = {}

    def register(self, entry_id: str, ws: WebSocket) -> None:
        self._conns[entry_id] = ws

    def unregister(self, entry_id: str) -> None:
        self._conns.pop(entry_id, None)

    async def notify(self, entry_id: str, payload: dict) -> None:
        ws = self._conns.get(entry_id)
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:
            pass
