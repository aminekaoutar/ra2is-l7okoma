from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from .enums import CardType, GameMode, GameStatus, PhaseType, PlayerSlot, RoundWinner

INTRO_DURATION = 60
DISCUSSION_DURATION = 300  # each debater gets their own full 5 minutes, not a shared pool
CLOSING_DURATION = 120

DIRECT_QUESTION_WINDOW = 30
INTERRUPT_WINDOW = 15
SECOND_QUESTION_TIMEOUT = 60
SECOND_QUESTION_CHOICES = 5

ALL_CARDS = [
    CardType.EXTRA_MINUTE,
    CardType.DIRECT_QUESTION,
    CardType.INTERRUPT,
    CardType.YIELD_TURN,
    CardType.CHALLENGE,
]


@dataclass
class Topic:
    id: str
    category: str
    question: str


@dataclass
class Player:
    slot: PlayerSlot
    name: str
    cards_used: dict[CardType, bool] = field(
        default_factory=lambda: {c: False for c in ALL_CARDS}
    )
    personal_remaining: int = INTRO_DURATION
    score: int = 0


@dataclass
class Interruption:
    card_type: CardType
    from_slot: PlayerSlot
    target_slot: PlayerSlot
    remaining: int
    resumes_running: bool


@dataclass
class PendingRequest:
    """An action one player asked for that needs the other player's consent
    before it takes effect — there's no moderator anymore to just allow it."""

    kind: str  # currently only "reset_timer"
    requested_by: PlayerSlot


@dataclass
class Game:
    id: str
    player1: Player
    player2: Player
    total_rounds: int = 3
    round_no: int = 1
    status: GameStatus = GameStatus.SETUP
    phase: PhaseType = PhaseType.INTRO
    active_slot: PlayerSlot = PlayerSlot.PLAYER1
    turn_index: int = 0  # 0 = player1's turn, 1 = player2's turn, for every phase
    running: bool = False
    current_topic: Optional[Topic] = None
    used_topic_ids: list[str] = field(default_factory=list)
    interruption: Optional[Interruption] = None
    log: list[str] = field(default_factory=list)
    round_winners: list[RoundWinner] = field(default_factory=list)
    mode: GameMode = GameMode.MODERATED
    round_categories: list[Optional[str]] = field(default_factory=list)
    category_for_round: Optional[str] = None
    pending_request: Optional[PendingRequest] = None

    # second question per round: chosen/written by one debater, or timed out to random
    chooser_for_round: list[Optional[PlayerSlot]] = field(default_factory=list)
    second_topic: Optional[Topic] = None
    choosing_slot: Optional[PlayerSlot] = None
    choosing_candidates: list[Topic] = field(default_factory=list)
    choosing_deadline: int = 0

    # pre-round green room: both mics are open here regardless of turn,
    # and the round only actually starts once both sides confirm ready
    ready_player1: bool = False
    ready_player2: bool = False

    @staticmethod
    def new(
        name1: str,
        name2: str,
        total_rounds: int,
        mode: GameMode = GameMode.MODERATED,
        round_categories: Optional[list[Optional[str]]] = None,
        chooser_for_round: Optional[list[Optional[PlayerSlot]]] = None,
    ) -> "Game":
        return Game(
            id=uuid.uuid4().hex[:10],
            player1=Player(slot=PlayerSlot.PLAYER1, name=name1),
            player2=Player(slot=PlayerSlot.PLAYER2, name=name2),
            total_rounds=total_rounds,
            mode=mode,
            round_categories=round_categories or [],
            chooser_for_round=chooser_for_round or [],
        )

    def player(self, slot: PlayerSlot) -> Player:
        return self.player1 if slot == PlayerSlot.PLAYER1 else self.player2

    def opponent_slot(self, slot: PlayerSlot) -> PlayerSlot:
        return PlayerSlot.PLAYER2 if slot == PlayerSlot.PLAYER1 else PlayerSlot.PLAYER1

    def add_log(self, message: str) -> None:
        self.log.insert(0, message)
        self.log = self.log[:60]
