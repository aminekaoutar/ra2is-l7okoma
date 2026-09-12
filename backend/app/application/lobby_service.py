from __future__ import annotations

from typing import Optional, TypedDict

from ..domain import rules
from ..domain.enums import GameMode
from ..domain.lobby import LobbyEntry, is_compatible
from .game_service import GameService
from .lobby_ports import LobbyNotifier, LobbyRepository


class MatchInfo(TypedDict):
    game_id: str
    waiting_entry_id: str
    waiting_slot: str
    joining_slot: str


class LobbyService:
    def __init__(self, repo: LobbyRepository, game_service: GameService, notifier: LobbyNotifier) -> None:
        self.repo = repo
        self.game_service = game_service
        self.notifier = notifier

    def _find_match(self, entry: LobbyEntry) -> Optional[LobbyEntry]:
        for other in self.repo.all():
            if is_compatible(other, entry):
                return other
        return None

    def join(self, name: str, topics: list[str], round_count: int) -> tuple[LobbyEntry, Optional[MatchInfo]]:
        entry = LobbyEntry.new(name, topics, round_count)
        waiting = self._find_match(entry)
        if waiting is None:
            self.repo.add(entry)
            return entry, None

        self.repo.remove(waiting.id)
        round_categories, chooser_for_round = rules.build_round_plan(
            round_count, waiting.topics, entry.topics
        )
        game = self.game_service.create_game(
            name1=waiting.name,
            name2=entry.name,
            total_rounds=round_count,
            mode=GameMode.MATCHED,
            round_categories=round_categories,
            chooser_for_round=chooser_for_round,
        )
        return entry, MatchInfo(
            game_id=game.id,
            waiting_entry_id=waiting.id,
            waiting_slot="player1",
            joining_slot="player2",
        )

    def cancel(self, entry_id: str) -> None:
        self.repo.remove(entry_id)
