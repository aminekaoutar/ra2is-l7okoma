from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..application.game_service import GameNotFound, GameService
from ..domain.enums import CardType, PlayerSlot, RoundWinner
from ..domain.rules import DomainError
from .ws_manager import ConnectionManager


class CreateGameRequest(BaseModel):
    name1: str = Field(default="المترشح الأحمر", max_length=30)
    name2: str = Field(default="المترشح الأخضر", max_length=30)
    total_rounds: int = Field(default=3, ge=1, le=10)


def build_router(service: GameService, connections: ConnectionManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/categories")
    def get_categories():
        return {"categories": service.categories()}

    @router.post("/api/games")
    def create_game(req: CreateGameRequest):
        game = service.create_game(req.name1, req.name2, req.total_rounds)
        return {"game_id": game.id}

    @router.get("/api/games/{game_id}")
    def get_game(game_id: str):
        try:
            game = service.get_game(game_id)
        except GameNotFound:
            return {"error": "not_found"}
        return service.state(game)

    @router.websocket("/ws/{game_id}")
    async def ws_endpoint(websocket: WebSocket, game_id: str, slot: Optional[str] = None):
        try:
            game = service.get_game(game_id)
        except GameNotFound:
            await websocket.close(code=4404)
            return

        # In matched (peer-to-peer) games, the ?slot= query param locks this
        # connection to one side — it may never act on behalf of the other
        # player. Moderated (legacy local) connections omit it and keep
        # controlling both sides, unchanged.
        locked_slot: Optional[PlayerSlot] = PlayerSlot(slot) if slot else None

        had_peer = await connections.connect(game_id, websocket)
        await websocket.send_json({"type": "state", **service.state(game)})
        if had_peer:
            # Both sides are now actually connected — safe to start WebRTC
            # signaling. Tell the new arrival directly, and let the side
            # that was already here (and previously had no one to call) know too.
            await websocket.send_json({"type": "peer_status", "present": True})
            await connections.relay(game_id, websocket, {"type": "peer_status", "present": True})

        try:
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action")
                try:
                    if action == "start_game":
                        await service.start_game(game_id)
                    elif action == "draw_topic":
                        await service.draw_topic(game_id, msg.get("category"))
                    elif action == "set_running":
                        await service.set_running(game_id, bool(msg.get("running")))
                    elif action == "skip_phase":
                        if locked_slot is not None and locked_slot != game.active_slot:
                            await websocket.send_json(
                                {"type": "error", "message": "يمكن ليك غير تخطي دورك نتا، ماشي دور الخصم"}
                            )
                        else:
                            await service.skip_phase(game_id)
                    elif action == "set_ready":
                        ready_slot = locked_slot or PlayerSlot(msg["slot"])
                        await service.set_ready(game_id, ready_slot, bool(msg.get("ready")))
                    elif action == "reset_turn_timer":
                        await service.reset_turn_timer(game_id)
                    elif action == "request_action":
                        kind = msg.get("kind")
                        if locked_slot is None:
                            # No opponent identity on this connection (legacy
                            # moderated mode) — nobody else to ask, just do it.
                            if kind == "reset_timer":
                                await service.reset_turn_timer(game_id)
                        else:
                            await service.request_action(game_id, kind, locked_slot)
                    elif action == "resolve_request":
                        if locked_slot is not None:
                            await service.resolve_request(game_id, locked_slot, bool(msg.get("approve")))
                    elif action == "cancel_request":
                        if locked_slot is not None:
                            await service.cancel_request(game_id, locked_slot)
                    elif action == "choose_second_topic":
                        chooser_slot = locked_slot or PlayerSlot(msg["slot"])
                        await service.choose_second_topic(game_id, chooser_slot, msg["topic_id"])
                    elif action == "write_second_topic":
                        chooser_slot = locked_slot or PlayerSlot(msg["slot"])
                        await service.write_second_topic(game_id, chooser_slot, msg.get("text", ""))
                    elif action == "send_reaction":
                        reaction_slot = locked_slot or PlayerSlot(msg["slot"])
                        emoji = msg.get("emoji", "")
                        service.register_reaction(game_id, reaction_slot, emoji)
                        # The sender already showed their own reaction locally and
                        # instantly — only the other side needs the broadcast.
                        await connections.relay(
                            game_id, websocket, {"type": "reaction", "slot": reaction_slot.value, "emoji": emoji}
                        )
                    elif action == "play_card":
                        requested_slot = PlayerSlot(msg["slot"])
                        if locked_slot is not None and requested_slot != locked_slot:
                            await websocket.send_json(
                                {"type": "error", "message": "ماشي الدور ديالك، هادي كارطة ديال الخصم"}
                            )
                        else:
                            await service.play_card(game_id, requested_slot, CardType(msg["card"]))
                    elif action == "resolve_interruption":
                        await service.resolve_interruption_now(game_id)
                    elif action == "set_round_winner":
                        await service.set_round_winner(game_id, RoundWinner(msg["winner"]))
                    elif action == "next_round":
                        await service.next_round(game_id)
                    elif action == "rtc_signal":
                        await connections.relay(
                            game_id, websocket, {"type": "rtc_signal", "payload": msg.get("payload")}
                        )
                    else:
                        await websocket.send_json({"type": "error", "message": f"unknown action: {action}"})
                except (DomainError, KeyError, ValueError) as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
        except WebSocketDisconnect:
            connections.disconnect(game_id, websocket)

    return router
