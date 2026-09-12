from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..domain.lobby import LobbyEntry


class LobbyRepository(ABC):
    @abstractmethod
    def add(self, entry: LobbyEntry) -> None: ...

    @abstractmethod
    def remove(self, entry_id: str) -> None: ...

    @abstractmethod
    def all(self) -> list[LobbyEntry]: ...


class LobbyNotifier(ABC):
    @abstractmethod
    async def notify(self, entry_id: str, payload: dict) -> None: ...
