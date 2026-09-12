from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .application.game_service import GameService
from .application.lobby_service import LobbyService
from .infrastructure.api import build_router
from .infrastructure.lobby_api import build_lobby_router
from .infrastructure.lobby_ws import LobbyConnectionManager
from .infrastructure.repositories import (
    InMemoryGameRepository,
    InMemoryLobbyRepository,
    JsonTopicRepository,
)
from .infrastructure.ws_manager import ConnectionManager

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "topics.json"
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", BASE_DIR.parent / "frontend"))

TICK_INTERVAL = 1.0

repo = InMemoryGameRepository()
topics = JsonTopicRepository(DATA_PATH)
connections = ConnectionManager()
service = GameService(repo=repo, topics=topics, broadcaster=connections)

lobby_repo = InMemoryLobbyRepository()
lobby_connections = LobbyConnectionManager()
lobby_service = LobbyService(repo=lobby_repo, game_service=service, notifier=lobby_connections)


async def _tick_loop() -> None:
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        for game_id in service.active_game_ids():
            if connections.has_room(game_id):
                try:
                    await service.tick(game_id)
                except Exception:
                    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_tick_loop())
    yield
    task.cancel()


app = FastAPI(title="Ra2is L7okoma API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    # Avoid stale HTML/CSS/JS in the browser across redeploys during active development.
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# Order matters: "/ws/{game_id}" is a wildcard that would otherwise swallow
# "/ws/lobby" (treating "lobby" as a game id), so the specific lobby route
# must be registered first.
app.include_router(build_lobby_router(lobby_service, lobby_connections))
app.include_router(build_router(service, connections))


@app.get("/watch/{game_id}")
async def watch_page(game_id: str):
    # Same single-page app — app.js detects the /watch/ path on load and
    # switches into audience mode instead of showing the lobby.
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
