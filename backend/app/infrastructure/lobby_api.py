from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..application.lobby_service import LobbyService
from .lobby_ws import LobbyConnectionManager


def build_lobby_router(lobby_service: LobbyService, connections: LobbyConnectionManager) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/lobby")
    async def lobby_ws(websocket: WebSocket):
        await websocket.accept()
        entry_id: str | None = None
        try:
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action")

                if action == "join":
                    name = str(msg.get("name") or "").strip()[:24] or "مجهول"
                    topics = msg.get("topics") or []
                    round_count = msg.get("round_count")
                    expected_topics = {3: 1, 5: 2}.get(round_count)

                    if expected_topics is None:
                        await websocket.send_json(
                            {"type": "error", "message": "عدد الجولات خاصو يكون 3 ولا 5"}
                        )
                        continue
                    if len(topics) != expected_topics or len(set(topics)) != expected_topics:
                        word = "واحد" if expected_topics == 1 else "مختلفين"
                        await websocket.send_json(
                            {"type": "error", "message": f"خاصك تختار {expected_topics} موضوع {word}"}
                        )
                        continue

                    entry, match = lobby_service.join(name, topics, round_count)
                    entry_id = entry.id
                    connections.register(entry_id, websocket)

                    if match:
                        await websocket.send_json(
                            {"type": "matched", "game_id": match["game_id"], "slot": match["joining_slot"]}
                        )
                        await connections.notify(
                            match["waiting_entry_id"],
                            {"type": "matched", "game_id": match["game_id"], "slot": match["waiting_slot"]},
                        )
                    else:
                        await websocket.send_json({"type": "waiting"})

                elif action == "cancel":
                    if entry_id:
                        lobby_service.cancel(entry_id)
                        await websocket.send_json({"type": "cancelled"})

        except WebSocketDisconnect:
            if entry_id:
                lobby_service.cancel(entry_id)
                connections.unregister(entry_id)

    return router
