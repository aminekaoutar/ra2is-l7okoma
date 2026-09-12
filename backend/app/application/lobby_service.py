from __future__ import annotations

from typing import Optional, TypedDict

from ..domain.enums import GameMode, PlayerSlot
from ..domain.lobby import LobbyEntry, is_compatible
from .game_service import GameService
from .lobby_ports import LobbyNotifier, LobbyRepository


class MatchInfo(TypedDict):
    game_id: str
    waiting_entry_id: str
    waiting_slot: str
    joining_slot: str


def _build_round_plan(waiting: LobbyEntry, entry: LobbyEntry) -> tuple[list[Optional[str]], list[Optional[PlayerSlot]]]:
    """Every topic each person picked gets its own round — nothing picked
    is ever wasted — plus one fully-random round at the end. 3 rounds means
    each person picked exactly 1 topic; 5 rounds means each picked 2,
    interleaved so nobody's two rounds are back-to-back."""
    if waiting.round_count == 3:
        categories = [waiting.topics[0], entry.topics[0], None]
        choosers = [PlayerSlot.PLAYER1, PlayerSlot.PLAYER2, None]
    else:  # 5
        categories = [
            waiting.topics[0],
            entry.topics[0],
            waiting.topics[1],
            entry.topics[1],
            None,
        ]
        choosers = [
            PlayerSlot.PLAYER1,
            PlayerSlot.PLAYER2,
            PlayerSlot.PLAYER1,
            PlayerSlot.PLAYER2,
            None,
        ]
    return categories, choosers


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
        round_categories, chooser_for_round = _build_round_plan(waiting, entry)
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
