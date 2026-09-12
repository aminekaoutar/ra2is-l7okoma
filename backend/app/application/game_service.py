from __future__ import annotations

import time
from typing import Optional

from ..domain import rules
from ..domain.enums import CardType, GameMode, GameStatus, PhaseType, PlayerSlot, RoundWinner
from ..domain.models import Game
from ..domain.rules import DomainError
from .ports import Broadcaster, GameRepository, TopicRepository

ALLOWED_REACTIONS = ("👍", "👎", "😂", "😮", "👏", "🤔")
REACTION_COOLDOWN_SECONDS = 2.5


class GameNotFound(Exception):
    pass


class GameService:
    def __init__(
        self,
        repo: GameRepository,
        topics: TopicRepository,
        broadcaster: Broadcaster,
    ) -> None:
        self.repo = repo
        self.topics = topics
        self.broadcaster = broadcaster
        self._last_reaction_at: dict[str, float] = {}  # key: f"{game_id}:{slot}"

    # ---------------------------------------------------------- helpers

    def _get(self, game_id: str) -> Game:
        game = self.repo.get(game_id)
        if game is None:
            raise GameNotFound(game_id)
        return game

    def get_game(self, game_id: str) -> Game:
        return self._get(game_id)

    async def _save_and_broadcast(self, game: Game) -> None:
        self.repo.save(game)
        await self.broadcaster.broadcast(game.id, {"type": "state", **self.state(game)})

    # -------------------------------------------------------- use cases

    def create_game(
        self,
        name1: str,
        name2: str,
        total_rounds: int,
        mode: GameMode = GameMode.MODERATED,
        round_categories: Optional[list[Optional[str]]] = None,
        chooser_for_round: Optional[list[Optional[PlayerSlot]]] = None,
    ) -> Game:
        game = Game.new(
            name1,
            name2,
            total_rounds,
            mode=mode,
            round_categories=round_categories,
            chooser_for_round=chooser_for_round,
        )
        self.repo.save(game)
        return game

    def categories(self) -> list[str]:
        return self.topics.categories()

    def _setup_round_questions(self, game: Game) -> None:
        """Matched (peer-to-peer) games have no moderator to click 'draw topic' —
        each round's category was already fixed at match time, so pull the
        first question the moment the round begins. The second question is
        deliberately NOT touched here — showing both at once confused
        people, so it's revealed later, right as the round moves into its
        closing phase (see _maybe_reveal_second_question)."""
        if game.mode != GameMode.MATCHED:
            return
        if game.current_topic is None:
            topic = rules.draw_topic(game, self.topics.all(), game.category_for_round)
            game.add_log(f"السؤال: [{topic.category}] {topic.question}")

    def _maybe_reveal_second_question(self, game: Game) -> None:
        """Called after any action that might have just moved the round into
        its closing phase. Only fires once per round: opens the 60s
        pick/write window for the round's designated chooser, or — for the
        fully-random round with no chooser — draws the second question
        immediately at random."""
        if game.mode != GameMode.MATCHED:
            return
        if game.phase != PhaseType.CLOSING:
            return
        if game.status != GameStatus.ACTIVE:
            return
        if game.second_topic is not None or game.choosing_slot is not None:
            return

        idx = game.round_no - 1
        chooser = game.chooser_for_round[idx] if idx < len(game.chooser_for_round) else None
        if chooser is not None:
            candidates = rules.pick_second_candidates(game, self.topics.all())
            rules.begin_choosing_second(game, chooser, candidates)
            game.add_log(f"⏳ {game.player(chooser).name} خاصو يختار ولا يكتب السؤال الثاني — 60 ثانية")
        else:
            topic2 = rules.draw_second_topic_random(game, self.topics.all())
            if topic2:
                game.add_log(f"السؤال الثاني: [{topic2.category}] {topic2.question}")

    async def start_game(self, game_id: str) -> dict:
        game = self._get(game_id)
        rules.start_game(game)
        game.add_log("افتتحت الجلسة")
        self._setup_round_questions(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def set_ready(self, game_id: str, slot: PlayerSlot, ready: bool) -> dict:
        game = self._get(game_id)
        both_ready = rules.set_ready(game, slot, ready)
        if ready:
            game.add_log(f"✅ {game.player(slot).name} مستعد")
        if both_ready:
            rules.start_game(game)
            game.add_log("الجميع مستعد — بدات الجلسة")
            self._setup_round_questions(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def draw_topic(self, game_id: str, category: Optional[str] = None) -> dict:
        game = self._get(game_id)
        topic = rules.draw_topic(game, self.topics.all(), category or game.category_for_round)
        game.add_log(f"الموضوع: [{topic.category}] {topic.question}")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def set_running(self, game_id: str, running: bool) -> dict:
        game = self._get(game_id)
        rules.set_running(game, running)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def skip_phase(self, game_id: str) -> dict:
        game = self._get(game_id)
        rules.advance_turn(game)
        self._maybe_reveal_second_question(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def reset_turn_timer(self, game_id: str) -> dict:
        game = self._get(game_id)
        rules.reset_turn_timer(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def request_action(self, game_id: str, kind: str, slot: PlayerSlot) -> dict:
        game = self._get(game_id)
        rules.request_pending(game, kind, slot)
        label = {"reset_timer": "يعاود الوقت ديال دورو"}.get(kind, kind)
        game.add_log(f"⏳ {game.player(slot).name} طلب {label} — كينتظر موافقة الخصم")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def resolve_request(self, game_id: str, slot: PlayerSlot, approve: bool) -> dict:
        game = self._get(game_id)
        requester = game.pending_request.requested_by if game.pending_request else None
        rules.resolve_pending(game, slot, approve)
        if requester is not None:
            verb = "✅ وافق" if approve else "❌ رفض"
            game.add_log(f"{verb} {game.player(slot).name} على الطلب")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def cancel_request(self, game_id: str, slot: PlayerSlot) -> dict:
        game = self._get(game_id)
        rules.cancel_pending(game, slot)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def choose_second_topic(self, game_id: str, slot: PlayerSlot, topic_id: str) -> dict:
        game = self._get(game_id)
        rules.choose_second_topic(game, slot, topic_id)
        game.add_log(f"السؤال الثاني: [{game.second_topic.category}] {game.second_topic.question}")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def write_second_topic(self, game_id: str, slot: PlayerSlot, text: str) -> dict:
        game = self._get(game_id)
        rules.write_second_topic(game, slot, text)
        game.add_log(f"✍️ {game.player(slot).name} كتب السؤال الثاني: {game.second_topic.question}")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def play_card(self, game_id: str, slot: PlayerSlot, card: CardType) -> dict:
        game = self._get(game_id)
        rules.play_card(game, slot, card)
        self._maybe_reveal_second_question(game)  # yield_turn can end the round's last discussion turn
        await self._save_and_broadcast(game)
        return self.state(game)

    async def cast_vote(self, game_id: str, audience_id: str, winner: PlayerSlot) -> dict:
        game = self._get(game_id)
        rules.cast_vote(game, audience_id, winner)
        game.add_log(f"🗳️ صوت جديد لـ {game.player(winner).name}")
        await self._save_and_broadcast(game)
        return self.state(game)

    async def submit_rematch_topics(self, game_id: str, slot: PlayerSlot, topics: list[str]) -> Optional[str]:
        """Both debaters independently pick fresh topics for a rematch — no
        lobby, no re-matching with a stranger, same two people again. Once
        both have submitted, a brand new game is created for them and its id
        is stashed on the old (finished) game so late joiners can follow."""
        game = self._get(game_id)
        rules.record_rematch_pick(game, slot, tuple(topics))
        game.add_log(f"🔁 {game.player(slot).name} اختار مواضيع لمناظرة جديدة")

        if not rules.rematch_ready(game):
            await self._save_and_broadcast(game)
            return None

        if rules.rematch_topics_conflict(game):
            rules.clear_rematch_pick(game, slot)
            await self._save_and_broadcast(game)
            raise DomainError("المواضيع ديالك كتلاقى مع مواضيع الخصم، ختار حاجة أخرى")

        round_categories, chooser_for_round = rules.build_round_plan(
            game.total_rounds,
            game.rematch_picks[PlayerSlot.PLAYER1],
            game.rematch_picks[PlayerSlot.PLAYER2],
        )
        new_game = self.create_game(
            name1=game.player1.name,
            name2=game.player2.name,
            total_rounds=game.total_rounds,
            mode=game.mode,
            round_categories=round_categories,
            chooser_for_round=chooser_for_round,
        )
        game.next_game_id = new_game.id
        game.add_log("🔁 بدات مناظرة جديدة بين نفس الطرفين")
        await self._save_and_broadcast(game)
        return new_game.id

    def register_reaction(self, game_id: str, sender_key: str, emoji: str) -> None:
        """A lightweight emoji reaction — doesn't touch the game state or
        timers at all (unlike the interruption cards). Only validates and
        rate-limits here; the caller relays it to everyone else directly
        (the sender already showed it locally, instantly). sender_key is a
        player's slot value or an audience member's id — anything unique
        enough to rate-limit independently per sender."""
        self._get(game_id)  # raises GameNotFound if the game doesn't exist
        if emoji not in ALLOWED_REACTIONS:
            raise DomainError("هاد الإيموجي ماشي متاح")
        key = f"{game_id}:{sender_key}"
        now = time.monotonic()
        last = self._last_reaction_at.get(key, 0.0)
        if now - last < REACTION_COOLDOWN_SECONDS:
            raise DomainError("تسنى شوية قبل ما تعاود ترياكت")
        self._last_reaction_at[key] = now

    async def resolve_interruption_now(self, game_id: str) -> dict:
        game = self._get(game_id)
        rules.resolve_interruption(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def set_round_winner(self, game_id: str, winner: RoundWinner) -> dict:
        game = self._get(game_id)
        rules.set_round_winner(game, winner)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def next_round(self, game_id: str) -> dict:
        game = self._get(game_id)
        rules.next_round(game)
        if game.status == GameStatus.ACTIVE:
            game.add_log(f"بدات الجولة {game.round_no}")
            self._setup_round_questions(game)
        await self._save_and_broadcast(game)
        return self.state(game)

    async def tick(self, game_id: str) -> Optional[dict]:
        game = self.repo.get(game_id)
        if game is None:
            return None
        if game.status != GameStatus.CHOOSING_SECOND and not game.running and game.interruption is None:
            return None
        rules.tick(game)
        self._maybe_reveal_second_question(game)  # natural timeout can end the round's last discussion turn
        await self._save_and_broadcast(game)
        return self.state(game)

    def active_game_ids(self) -> list[str]:
        return self.repo.all_active_ids()

    # ------------------------------------------------------- serializer

    def state(self, game: Game) -> dict:
        def player_dict(p, ready):
            return {
                "slot": p.slot.value,
                "name": p.name,
                "score": p.score,
                "personal_remaining": p.personal_remaining,
                "cards_used": {c.value: used for c, used in p.cards_used.items()},
                "ready": ready,
            }

        interruption = None
        if game.interruption:
            i = game.interruption
            interruption = {
                "card_type": i.card_type.value,
                "from_slot": i.from_slot.value,
                "target_slot": i.target_slot.value,
                "remaining": i.remaining,
            }

        return {
            "id": game.id,
            "mode": game.mode.value,
            "status": game.status.value,
            "phase": game.phase.value,
            "round_no": game.round_no,
            "total_rounds": game.total_rounds,
            "active_slot": game.active_slot.value,
            "running": game.running,
            "current_topic": (
                {
                    "id": game.current_topic.id,
                    "category": game.current_topic.category,
                    "question": game.current_topic.question,
                }
                if game.current_topic
                else None
            ),
            "second_topic": (
                {
                    "id": game.second_topic.id,
                    "category": game.second_topic.category,
                    "question": game.second_topic.question,
                }
                if game.second_topic
                else None
            ),
            "choosing_slot": game.choosing_slot.value if game.choosing_slot else None,
            "choosing_candidates": [
                {"id": t.id, "category": t.category, "question": t.question} for t in game.choosing_candidates
            ],
            "choosing_deadline": game.choosing_deadline,
            "interruption": interruption,
            "pending_request": (
                {"kind": game.pending_request.kind, "requested_by": game.pending_request.requested_by.value}
                if game.pending_request
                else None
            ),
            "player1": player_dict(game.player1, game.ready_player1),
            "player2": player_dict(game.player2, game.ready_player2),
            "round_winners": [w.value for w in game.round_winners],
            "log": game.log[:20],
            "vote_player1": game.vote_player1,
            "vote_player2": game.vote_player2,
            "rematch_submitted": {
                "player1": PlayerSlot.PLAYER1 in game.rematch_picks,
                "player2": PlayerSlot.PLAYER2 in game.rematch_picks,
            },
            "next_game_id": game.next_game_id,
        }
