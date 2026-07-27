"""Last-Write-Wins CRDT primitives.

Used for non-geometry fields (parcel name, description, metadata). Two
peers can edit independently and converge deterministically using a
hybrid logical clock + actor id tiebreaker.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


def _now_ns() -> int:
    return time.time_ns()


@dataclass(frozen=True, slots=True)
class LWWStamp:
    """A hybrid timestamp + actor id used to compare writes."""

    ts: int
    actor: str

    def __lt__(self, other: LWWStamp) -> bool:
        if self.ts != other.ts:
            return self.ts < other.ts
        return self.actor < other.actor


@dataclass(slots=True)
class LWWRegister:
    """A single LWW-Register cell."""

    actor: str
    value: Any = None
    stamp: LWWStamp | None = None

    def set(self, value: Any) -> LWWStamp:
        stamp = LWWStamp(ts=_now_ns(), actor=self.actor)
        self.value = value
        self.stamp = stamp
        return stamp

    def merge(self, other_value: Any, other_stamp: LWWStamp) -> bool:
        """Adopt ``other`` if it's strictly newer. Returns True if changed."""
        if self.stamp is None or self.stamp < other_stamp:
            self.value = other_value
            self.stamp = other_stamp
            return True
        return False


@dataclass(slots=True)
class LWWMap:
    """A Map<String, LWWRegister>."""

    actor: str
    cells: dict[str, LWWRegister] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> LWWStamp:
        cell = self.cells.get(key) or LWWRegister(actor=self.actor)
        stamp = cell.set(value)
        self.cells[key] = cell
        return stamp

    def get(self, key: str, default: Any = None) -> Any:
        cell = self.cells.get(key)
        return cell.value if cell is not None else default

    def merge(self, other: LWWMap) -> int:
        """Merge ``other``'s cells into ``self``. Returns count of changed keys."""
        changed = 0
        for k, cell in other.cells.items():
            here = self.cells.get(k) or LWWRegister(actor=self.actor)
            if cell.stamp is None:
                continue
            if here.merge(cell.value, cell.stamp):
                changed += 1
            self.cells[k] = here
        return changed

    def items(self) -> Iterator[tuple[str, Any]]:
        for k, cell in self.cells.items():
            yield k, cell.value
