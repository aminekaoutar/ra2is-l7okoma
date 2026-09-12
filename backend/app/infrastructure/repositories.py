from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from ..application.lobby_ports import LobbyRepository
from ..application.ports import GameRepository, TopicRepository
from ..domain.enums import GameStatus
from ..domain.lobby import LobbyEntry
from ..domain.models import Game, Topic


class InMemoryGameRepository(GameRepository):
    """Simple process-local store. Swap for a Redis/DB adapter to scale
    beyond a single instance — the application layer never needs to know.
    """

    def __init__(self) -> None:
        self._games: dict[str, Game] = {}
        self._lock = threading.Lock()

    def save(self, game: Game) -> None:
        with self._lock:
            self._games[game.id] = game

    def get(self, game_id: str) -> Optional[Game]:
        with self._lock:
            return self._games.get(game_id)

    def all_active_ids(self) -> list[str]:
        with self._lock:
            return [
                gid
                for gid, g in self._games.items()
                if g.status in (GameStatus.ACTIVE, GameStatus.CHOOSING_SECOND)
            ]

    def delete(self, game_id: str) -> None:
        with self._lock:
            self._games.pop(game_id, None)


class JsonTopicRepository(TopicRepository):
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._topics = [Topic(id=t["id"], category=t["category"], question=t["question"]) for t in raw]

    def all(self) -> list[Topic]:
        return list(self._topics)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for t in self._topics:
            if t.category not in seen:
                seen.append(t.category)
        return seen


class InMemoryLobbyRepository(LobbyRepository):
    def __init__(self) -> None:
        self._waiting: dict[str, LobbyEntry] = {}
        self._lock = threading.Lock()

    def add(self, entry: LobbyEntry) -> None:
        with self._lock:
            self._waiting[entry.id] = entry

    def remove(self, entry_id: str) -> None:
        with self._lock:
            self._waiting.pop(entry_id, None)

    def all(self) -> list[LobbyEntry]:
        with self._lock:
            return list(self._waiting.values())
