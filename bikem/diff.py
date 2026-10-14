"""Structural diff between two recorded bikem sessions.

Answers: "these two runs behaved differently -- where did they first diverge?"

Only behavior-bearing events are compared. Session metadata (session.start,
session.end) is intentionally ignored -- two sessions with the same LLM and
tool activity are identical for debugging purposes, even if their names or
pids differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import Event, EventType, compute_hash
from .store import load_session

# Event types that carry behavior. Everything else is metadata.
_MEANINGFUL = {
    EventType.LLM_REQUEST.value,
    EventType.LLM_RESPONSE.value,
    EventType.TOOL_CALL.value,
    EventType.TOOL_RESULT.value,
    EventType.CONTEXT_INJECT.value,
    EventType.DRIFT_FLAG.value,
    EventType.ERROR.value,
}


@dataclass
class EventDiff:
    """One point of divergence between two sessions."""

    seq: int
    kind: str  # "type_mismatch" | "content_mismatch" | "missing" | "extra"
    detail: str
    left: Event | None = None
    right: Event | None = None


@dataclass
class DiffResult:
    """Result of comparing two sessions."""

    left_id: str
    right_id: str
    left_count: int
    right_count: int
    divergences: list[EventDiff] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not self.divergences

    @property
    def first(self) -> EventDiff | None:
        return self.divergences[0] if self.divergences else None


def _fingerprint(ev: Event) -> str:
    """Content hash of an event, ignoring session identity.

    Two events with the same type and the same payload produce the same
    fingerprint -- even if recorded minutes apart in different sessions.
    """
    return compute_hash("", {"type": ev.type, "payload": ev.payload or {}})


def _meaningful(events: list[Event]) -> list[Event]:
    """Keep only behavior-bearing events, drop session metadata."""
    return [e for e in events if e.type in _MEANINGFUL]


def diff_sessions(left_id: str, right_id: str, root: Any = None) -> DiffResult:
    """Compare two sessions by id. Returns a DiffResult."""
    left_all = load_session(left_id, root=root)
    right_all = load_session(right_id, root=root)
    left = _meaningful(left_all)
    right = _meaningful(right_all)

    result = DiffResult(
        left_id=left_id,
        right_id=right_id,
        left_count=len(left_all),
        right_count=len(right_all),
    )

    n = max(len(left), len(right))
    for i in range(n):
        left_ev = left[i] if i < len(left) else None
        right_ev = right[i] if i < len(right) else None
        pos = i + 1

        if left_ev is None:
            assert right_ev is not None
            result.divergences.append(
                EventDiff(
                    seq=right_ev.seq,
                    kind="extra",
                    detail=f"right has event at position {pos} ({right_ev.type})",
                    right=right_ev,
                )
            )
            continue

        if right_ev is None:
            result.divergences.append(
                EventDiff(
                    seq=left_ev.seq,
                    kind="missing",
                    detail=f"left has event at position {pos} ({left_ev.type})",
                    left=left_ev,
                )
            )
            continue

        if left_ev.type != right_ev.type:
            result.divergences.append(
                EventDiff(
                    seq=left_ev.seq,
                    kind="type_mismatch",
                    detail=f"left is {left_ev.type}, right is {right_ev.type}",
                    left=left_ev,
                    right=right_ev,
                )
            )
            continue

        if _fingerprint(left_ev) != _fingerprint(right_ev):
            result.divergences.append(
                EventDiff(
                    seq=left_ev.seq,
                    kind="content_mismatch",
                    detail=f"same type ({left_ev.type}) but different content",
                    left=left_ev,
                    right=right_ev,
                )
            )

    return result


def summarize(result: DiffResult) -> str:
    """One-line English summary of a diff result."""
    if result.identical:
        return f"identical ({result.left_count} events)"
    first = result.first
    assert first is not None
    return f"{len(result.divergences)} divergence(s) -- first at #{first.seq} ({first.kind})"
