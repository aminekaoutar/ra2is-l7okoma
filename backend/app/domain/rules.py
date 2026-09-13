"""Pure domain rules for the Ra2is L7okoma debate game.

No framework, no I/O — just state transitions over the Game aggregate.
"""
from __future__ import annotations

import random
import uuid
from typing import Optional

from .enums import CardType, GameStatus, PhaseType, PlayerSlot, RoundWinner
from .models import (
    CLOSING_DURATION,
    DISCUSSION_DURATION,
    INTERRUPT_WINDOW,
    DIRECT_QUESTION_WINDOW,
    INTRO_DURATION,
    SECOND_QUESTION_CHOICES,
    SECOND_QUESTION_TIMEOUT,
    Game,
    Interruption,
    PendingRequest,
    Topic,
)


class DomainError(Exception):
    pass


def phase_turn_duration(phase: PhaseType) -> int:
    """Every phase now works the same way: each debater gets their own full
    allowance, one after the other — 1:00 / 5:00 / 2:00 respectively."""
    return {
        PhaseType.INTRO: INTRO_DURATION,
        PhaseType.DISCUSSION: DISCUSSION_DURATION,
        PhaseType.CLOSING: CLOSING_DURATION,
    }[phase]


# ---------------------------------------------------------------- lifecycle

def begin_round(game: Game) -> None:
    game.phase = PhaseType.INTRO
    game.turn_index = 0
    game.active_slot = PlayerSlot.PLAYER1
    game.player1.personal_remaining = INTRO_DURATION
    game.player2.personal_remaining = INTRO_DURATION
    game.current_topic = None
    # second_topic is deliberately NOT cleared here: it's how the previous
    # round's end-of-round pick hands the upcoming round its topic (see
    # GameService._setup_round_questions, which consumes and clears it).
    game.choosing_slot = None
    game.choosing_candidates = []
    game.choosing_deadline = 0
    game.interruption = None
    game.running = False
    idx = game.round_no - 1
    game.category_for_round = (
        game.round_categories[idx] if idx < len(game.round_categories) else None
    )


def start_game(game: Game) -> None:
    if game.status != GameStatus.SETUP:
        raise DomainError("Game already started")
    game.status = GameStatus.ACTIVE
    begin_round(game)


def set_ready(game: Game, slot: PlayerSlot, ready: bool) -> bool:
    """Pre-round green room: mark one side ready. Returns True once both
    sides are — the caller is responsible for actually starting the game."""
    if game.status != GameStatus.SETUP:
        raise DomainError("الجلسة بدات ديجا")
    if slot == PlayerSlot.PLAYER1:
        game.ready_player1 = ready
    else:
        game.ready_player2 = ready
    return game.ready_player1 and game.ready_player2


def _enter_phase(game: Game, phase: PhaseType) -> None:
    game.phase = phase
    game.running = False
    game.interruption = None
    game.turn_index = 0
    game.active_slot = PlayerSlot.PLAYER1
    duration = phase_turn_duration(phase)
    game.player1.personal_remaining = duration
    game.player2.personal_remaining = duration


def advance_turn(game: Game) -> None:
    """End the active speaker's turn now — every phase is two sequential
    turns (player1 then player2), so this is the one place that handles
    'this speaker is done': natural timeout, the yield_turn card, and the
    moderator's skip button all funnel through here."""
    if game.turn_index == 0:
        game.turn_index = 1
        game.active_slot = PlayerSlot.PLAYER2
        game.player2.personal_remaining = phase_turn_duration(game.phase)
        game.running = False
    else:
        _end_phase(game)


def _end_phase(game: Game) -> None:
    if game.phase == PhaseType.INTRO:
        _enter_phase(game, PhaseType.DISCUSSION)
    elif game.phase == PhaseType.DISCUSSION:
        _enter_phase(game, PhaseType.CLOSING)
    elif game.phase == PhaseType.CLOSING:
        game.status = GameStatus.ROUND_END
        game.running = False


def reset_turn_timer(game: Game) -> None:
    game.player(game.active_slot).personal_remaining = phase_turn_duration(game.phase)


def set_running(game: Game, running: bool) -> None:
    if running and game.status != GameStatus.ACTIVE:
        raise DomainError("تسنى — مازال كاين شي حاجة خاصها تتسالا قبل ما تبدا")
    if running and game.current_topic is None:
        raise DomainError("لازم تسحب موضوع قبل ما تبدا")
    if running and game.interruption is not None:
        raise DomainError("كاين استجواب واقف، خاصك تسالو قبل")
    game.running = running


# ------------------------------------------------------------ mutual consent

def request_pending(game: Game, kind: str, requested_by: PlayerSlot) -> None:
    if game.pending_request is not None:
        raise DomainError("كاين طلب واقف ديجا، تسنى شوية")
    if kind == "reset_timer" and game.active_slot != requested_by:
        raise DomainError("يمكن ليك غير تعاود الوقت ديال دورك نتا")
    game.pending_request = PendingRequest(kind=kind, requested_by=requested_by)


def resolve_pending(game: Game, responder: PlayerSlot, approve: bool) -> None:
    if game.pending_request is None:
        raise DomainError("ماكاين حتى طلب دابا")
    if responder == game.pending_request.requested_by:
        raise DomainError("معندكش تصوت على الطلب ديالك نتا")
    kind = game.pending_request.kind
    game.pending_request = None
    if approve and kind == "reset_timer":
        reset_turn_timer(game)


def cancel_pending(game: Game, slot: PlayerSlot) -> None:
    if game.pending_request is None or game.pending_request.requested_by != slot:
        raise DomainError("ماكاينش طلب ديالك باش تلغيه")
    game.pending_request = None


# ------------------------------------------------------------------ topics

def draw_topic(game: Game, pool: list[Topic], category: Optional[str] = None) -> Topic:
    candidates = [t for t in pool if (category is None or t.category == category)]
    fresh = [t for t in candidates if t.id not in game.used_topic_ids]
    if not fresh:
        game.used_topic_ids = [t.id for t in game.used_topic_ids if False]  # clear
        fresh = candidates
    if not fresh:
        raise DomainError("ما كاينش مواضيع فهاد الفئة")
    topic = random.choice(fresh)
    game.current_topic = topic
    game.used_topic_ids.append(topic.id)
    return topic


# --------------------------------------------------------- second question

def pick_second_candidates(
    game: Game, pool: list[Topic], category: Optional[str], count: int = SECOND_QUESTION_CHOICES
) -> list[Topic]:
    exclude_ids = set(game.used_topic_ids)
    candidates = [
        t for t in pool if (category is None or t.category == category) and t.id not in exclude_ids
    ]
    random.shuffle(candidates)
    return candidates[:count]


def begin_choosing_second(game: Game, chooser: PlayerSlot, candidates: list[Topic]) -> None:
    game.status = GameStatus.CHOOSING_SECOND
    game.choosing_slot = chooser
    game.choosing_candidates = candidates
    game.choosing_deadline = SECOND_QUESTION_TIMEOUT


def _finish_choosing(game: Game) -> None:
    game.choosing_slot = None
    game.choosing_candidates = []
    game.choosing_deadline = 0
    # This only ever runs between rounds now (the pick determines the
    # UPCOMING round's topic), so the round being wrapped up stays over.
    game.status = GameStatus.ROUND_END


def choose_second_topic(game: Game, slot: PlayerSlot, topic_id: str) -> None:
    if game.status != GameStatus.CHOOSING_SECOND:
        raise DomainError("ماكاينش شي اختيار خاصو يتدار دابا")
    if slot != game.choosing_slot:
        raise DomainError("ماشي نتا اللي خاصك تختار السؤال الثاني")
    match = next((t for t in game.choosing_candidates if t.id == topic_id), None)
    if match is None:
        raise DomainError("هاد السؤال ماشي من بين الاختيارات")
    game.second_topic = match
    game.used_topic_ids.append(match.id)
    _finish_choosing(game)


def write_second_topic(game: Game, slot: PlayerSlot, text: str) -> None:
    if game.status != GameStatus.CHOOSING_SECOND:
        raise DomainError("ماكاينش شي اختيار خاصو يتدار دابا")
    if slot != game.choosing_slot:
        raise DomainError("ماشي نتا اللي خاصك تكتب السؤال الثاني")
    text = text.strip()
    if not text:
        raise DomainError("كتب سؤال ماشي فارغ")
    if len(text) > 220:
        raise DomainError("السؤال طويل بزاف")
    game.second_topic = Topic(
        id=f"custom-{uuid.uuid4().hex[:8]}",
        category=game.category_for_round or "سؤال مكتوب",
        question=text,
    )
    _finish_choosing(game)


def timeout_choosing_second(game: Game) -> None:
    if game.status != GameStatus.CHOOSING_SECOND:
        return
    if game.choosing_candidates:
        chosen = random.choice(game.choosing_candidates)
        game.second_topic = chosen
        game.used_topic_ids.append(chosen.id)
        game.add_log(f"⏰ خلص الوقت — تعطا عشوائيا: {chosen.question}")
    _finish_choosing(game)


def draw_second_topic_random(game: Game, pool: list[Topic], category: Optional[str]) -> Optional[Topic]:
    """For rounds with no designated chooser (e.g. the fully-random round) —
    the upcoming round's topic is still picked here, just at random instead
    of by a debater."""
    exclude_ids = set(game.used_topic_ids)
    candidates = [
        t for t in pool if (category is None or t.category == category) and t.id not in exclude_ids
    ]
    if not candidates:
        return None
    topic = random.choice(candidates)
    game.second_topic = topic
    game.used_topic_ids.append(topic.id)
    return topic


# -------------------------------------------------------------------- tick

def tick(game: Game) -> None:
    if game.status == GameStatus.CHOOSING_SECOND:
        game.choosing_deadline -= 1
        if game.choosing_deadline <= 0:
            timeout_choosing_second(game)
        return

    if game.interruption is not None:
        game.interruption.remaining -= 1
        if game.interruption.remaining <= 0:
            resolve_interruption(game)
        return

    if not game.running:
        return

    active = game.player(game.active_slot)
    active.personal_remaining -= 1
    if active.personal_remaining <= 0:
        active.personal_remaining = 0
        game.add_log(f"انتهى وقت {active.name}")
        advance_turn(game)


# ------------------------------------------------------------------- cards

def can_play_card(game: Game, slot: PlayerSlot, card: CardType) -> bool:
    if game.status != GameStatus.ACTIVE:
        return False
    player = game.player(slot)
    if player.cards_used[card]:
        return False
    if game.current_topic is None:
        return False
    opponent = game.opponent_slot(slot)

    if card == CardType.EXTRA_MINUTE:
        return game.active_slot == slot and game.running
    if card == CardType.YIELD_TURN:
        return game.active_slot == slot and game.running
    if card in (CardType.DIRECT_QUESTION, CardType.INTERRUPT, CardType.CHALLENGE):
        return game.active_slot == opponent and game.running and game.interruption is None
    return False


def start_interruption(game: Game, slot: PlayerSlot, card: CardType, window: int) -> None:
    opponent = game.opponent_slot(slot)
    resumes = game.running
    game.running = False
    game.interruption = Interruption(
        card_type=card,
        from_slot=slot,
        target_slot=opponent,
        remaining=window,
        resumes_running=resumes,
    )


def resolve_interruption(game: Game) -> None:
    if game.interruption is None:
        return
    resumes = game.interruption.resumes_running
    game.interruption = None
    game.running = resumes


def play_card(game: Game, slot: PlayerSlot, card: CardType) -> None:
    if not can_play_card(game, slot, card):
        raise DomainError("الكارطة ما يمكنش تتستعمل دابا")
    player = game.player(slot)
    player.cards_used[card] = True

    if card == CardType.EXTRA_MINUTE:
        player.personal_remaining += 60
        game.add_log(f"⏱ {player.name} استعمل بطاقة (زيد دقيقة)")
    elif card == CardType.YIELD_TURN:
        game.add_log(f"🤝 {player.name} استعمل بطاقة (بذل الدور)")
        player.personal_remaining = 0
        advance_turn(game)
    elif card == CardType.DIRECT_QUESTION:
        game.add_log(f"❓ {player.name} استعمل بطاقة (سؤال مباشر)")
        start_interruption(game, slot, card, DIRECT_QUESTION_WINDOW)
    elif card == CardType.INTERRUPT:
        game.add_log(f"✋ {player.name} استعمل بطاقة (قاطعني)")
        start_interruption(game, slot, card, INTERRUPT_WINDOW)
    elif card == CardType.CHALLENGE:
        opponent = game.player(game.opponent_slot(slot))
        game.add_log(f"🎯 {player.name} تحدى {opponent.name}: طالبو يبرر ادعاءه")


# -------------------------------------------------------------------- round

def set_round_winner(game: Game, winner: RoundWinner) -> None:
    if game.status != GameStatus.ROUND_END:
        raise DomainError("الجولة مازال ماشي سالاة")
    game.round_winners.append(winner)
    if winner == RoundWinner.PLAYER1:
        game.player1.score += 1
    elif winner == RoundWinner.PLAYER2:
        game.player2.score += 1


def next_round(game: Game) -> None:
    if game.status != GameStatus.ROUND_END:
        raise DomainError("الجولة مازال ماشي سالاة")
    if game.round_no >= game.total_rounds:
        game.status = GameStatus.FINISHED
        return
    game.round_no += 1
    game.status = GameStatus.ACTIVE
    begin_round(game)


def build_round_plan(
    round_count: int, topics_p1: tuple[str, ...], topics_p2: tuple[str, ...]
) -> tuple[list[Optional[str]], list[Optional[PlayerSlot]]]:
    """Every topic each person picked gets its own round — nothing picked
    is ever wasted — plus one fully-random round at the end. 3 rounds means
    each person picked exactly 1 topic; 5 rounds means each picked 2,
    interleaved so nobody's two rounds are back-to-back. Shared by lobby
    matching and rematches — same rule either way."""
    if round_count == 3:
        categories = [topics_p1[0], topics_p2[0], None]
        choosers = [PlayerSlot.PLAYER1, PlayerSlot.PLAYER2, None]
    else:  # 5
        categories = [topics_p1[0], topics_p2[0], topics_p1[1], topics_p2[1], None]
        choosers = [
            PlayerSlot.PLAYER1,
            PlayerSlot.PLAYER2,
            PlayerSlot.PLAYER1,
            PlayerSlot.PLAYER2,
            None,
        ]
    return categories, choosers


# ------------------------------------------------------------------- voting

def cast_vote(game: Game, audience_id: str, winner: PlayerSlot) -> None:
    if game.status != GameStatus.FINISHED:
        raise DomainError("التصويت غايبدا غير من بعد ما تسالا المناظرة")
    if audience_id in game.voted_audience_ids:
        raise DomainError("صوتيتي ديجا")
    game.voted_audience_ids.add(audience_id)
    if winner == PlayerSlot.PLAYER1:
        game.vote_player1 += 1
    else:
        game.vote_player2 += 1


# ------------------------------------------------------------------ rematch

def record_rematch_pick(game: Game, slot: PlayerSlot, topics: tuple[str, ...]) -> None:
    if game.status != GameStatus.FINISHED:
        raise DomainError("لازم المناظرة تكون سالات باش تعاودوها")
    if len(set(topics)) != len(topics):
        raise DomainError("خاصك تختار مواضيع مختلفة")
    game.rematch_picks[slot] = tuple(topics)


def rematch_ready(game: Game) -> bool:
    return PlayerSlot.PLAYER1 in game.rematch_picks and PlayerSlot.PLAYER2 in game.rematch_picks


def rematch_topics_conflict(game: Game) -> bool:
    p1 = set(game.rematch_picks.get(PlayerSlot.PLAYER1, ()))
    p2 = set(game.rematch_picks.get(PlayerSlot.PLAYER2, ()))
    return bool(p1 & p2)


def clear_rematch_pick(game: Game, slot: PlayerSlot) -> None:
    game.rematch_picks.pop(slot, None)
