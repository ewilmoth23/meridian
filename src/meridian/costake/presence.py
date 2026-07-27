"""Per-user presence (cursor + selection) tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Cursor:
    actor: str
    x: float
    y: float
    color_hex: str = "#ffd76e"
    label: str | None = None
    last_seen_ms: int = 0


@dataclass(slots=True)
class PresenceState:
    """Map of actor → :class:`Cursor`. Latest update wins; older are dropped
    after :attr:`stale_after_ms`.
    """

    cursors: dict[str, Cursor] = field(default_factory=dict)
    stale_after_ms: int = 30_000

    def update(self, cursor: Cursor) -> None:
        self.cursors[cursor.actor] = cursor

    def remove(self, actor: str) -> None:
        self.cursors.pop(actor, None)

    def active(self, now_ms: int) -> list[Cursor]:
        return [c for c in self.cursors.values() if now_ms - c.last_seen_ms <= self.stale_after_ms]
