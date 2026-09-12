"""Ports: the interfaces the application core depends on.
Adapters in infrastructure/ implement these — this is what makes the
architecture hexagonal (the domain/application never import infrastructure).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..domain.models import Game, Topic


class GameRepository(ABC):
    @abstractmethod
    def save(self, game: Game) -> None: ...

    @abstractmethod
    def get(self, game_id: str) -> Optional[Game]: ...

    @abstractmethod
    def all_active_ids(self) -> list[str]: ...

    @abstractmethod
    def delete(self, game_id: str) -> None: ...


class TopicRepository(ABC):
    @abstractmethod
    def all(self) -> list[Topic]: ...

    @abstractmethod
    def categories(self) -> list[str]: ...


class Broadcaster(ABC):
    @abstractmethod
    async def broadcast(self, game_id: str, payload: dict) -> None: ...
