"""Append-only JSONL store for bikem traces.

One file per session at $BIKEM_HOME/sessions/{session_id}.jsonl
($BIKEM_HOME defaults to ~/.bikem).

Lock-free by design: one writer per session. The store must never crash
the host application -- every I/O operation is best-effort.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from .events import (
    GENESIS_HASH,
    Event,
    EventType,
    make_event,
    new_session_id,
)

DEFAULT_ROOT = Path(os.environ.get("BIKEM_HOME", str(Path.home() / ".bikem")))


def _root(root: Path | str | None = None) -> Path:
    if root is None:
        return Path(os.environ.get("BIKEM_HOME", str(DEFAULT_ROOT)))
    return Path(root)


class SessionStore:
    """Append-only writer and reader for a single session."""

    def __init__(self, session_id: str | None = None, root: Path | str | None = None):
        self.session_id = session_id or new_session_id()
        self.root = _root(root)
        self.sessions_dir = self.root / "sessions"
        self.path = self.sessions_dir / (self.session_id + ".jsonl")
        self._seq = 0
        self._last_hash = GENESIS_HASH
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def append(
        self,
        event_type: EventType | str,
        payload: dict,
        parent_seq: int | None = None,
    ) -> Event:
        """Append an event. Returns the Event even if the write failed."""
        self._seq += 1
        ev = make_event(
            seq=self._seq,
            event_type=event_type,
            session_id=self.session_id,
            payload=payload,
            prev_hash=self._last_hash,
            parent_seq=parent_seq,
        )
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(ev.to_jsonl() + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass
        self._last_hash = ev.hash
        return ev

    @property
    def seq(self) -> int:
        return self._seq

    def read(self) -> list[Event]:
        return list(self.iter_events())

    def iter_events(self) -> Iterator[Event]:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield Event.from_dict(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            return


def list_sessions(root: Path | str | None = None) -> list[dict]:
    """Return metadata for every session, newest first."""
    base = _root(root) / "sessions"
    if not base.exists():
        return []
    out: list[dict] = []
    for p in sorted(base.glob("sess_*.jsonl")):
        try:
            stat = p.stat()
            out.append(
                {
                    "session_id": p.stem,
                    "path": str(p),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
        except Exception:
            continue
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def load_session(session_id: str, root: Path | str | None = None) -> list[Event]:
    return SessionStore(session_id=session_id, root=root).read()
