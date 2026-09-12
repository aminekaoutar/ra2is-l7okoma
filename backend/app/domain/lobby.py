from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


@dataclass
class LobbyEntry:
    id: str
    name: str
    topics: tuple[str, ...]
    round_count: int  # 3 (1 topic each) or 5 (2 topics each)
    joined_at: float

    @staticmethod
    def new(name: str, topics: list[str], round_count: int) -> "LobbyEntry":
        return LobbyEntry(
            id=uuid.uuid4().hex[:10],
            name=name,
            topics=tuple(topics),
            round_count=round_count,
            joined_at=time.time(),
        )


def is_compatible(a: LobbyEntry, b: LobbyEntry) -> bool:
    """Two people are matchable only if they picked the same match length
    (so their topic counts line up) and their topic picks are completely
    different from each other — no shared category at all."""
    return a.round_count == b.round_count and not (set(a.topics) & set(b.topics))
