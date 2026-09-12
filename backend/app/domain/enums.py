from enum import Enum


class CardType(str, Enum):
    EXTRA_MINUTE = "extra_minute"
    DIRECT_QUESTION = "direct_question"
    INTERRUPT = "interrupt"
    YIELD_TURN = "yield_turn"
    CHALLENGE = "challenge"


class PhaseType(str, Enum):
    INTRO = "intro"
    DISCUSSION = "discussion"
    CLOSING = "closing"


class PlayerSlot(str, Enum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"


class GameStatus(str, Enum):
    SETUP = "setup"
    CHOOSING_SECOND = "choosing_second"  # waiting on this round's second question
    ACTIVE = "active"
    ROUND_END = "round_end"
    FINISHED = "finished"


class GameMode(str, Enum):
    MODERATED = "moderated"  # one controller drives both sides (legacy local mode)
    MATCHED = "matched"  # two real peers matched from the lobby, topics preset, no judge


class RoundWinner(str, Enum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"
    TIE = "tie"
