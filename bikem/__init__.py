"""bikem -- local-first memory and drift detection for long AI sessions.

Public API:

    import bikem

    with bikem.session("my-session"):
        ...  # your existing code, unchanged

    # or manual control:
    with bikem.session("my-session") as s:
        print(s.session_id)
        print(s.trace_path)

Environment:

    BIKEM_HOME      storage root (default: ~/.bikem)
    BIKEM_DISABLE   set to "1" to make session() a no-op
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Iterator

from . import recorder
from .events import EventType, GENESIS_HASH, compute_hash, verify_chain
from .store import DEFAULT_ROOT, SessionStore, list_sessions, load_session

__version__ = "0.0.1"

__all__ = [
    "session",
    "Session",
    "SessionStore",
    "list_sessions",
    "load_session",
    "verify_chain",
    "__version__",
]


class Session:
    """A single recording session.

    Returned by bikem.session(). Exposes the session id and the on-disk
    trace path so callers can point at the file directly.
    """

    def __init__(self, name: str = "", store: SessionStore | None = None):
        self.name = name
        self.store = store or SessionStore()
        self._entered = False

    @property
    def session_id(self) -> str:
        return self.store.session_id

    @property
    def trace_path(self) -> Path:
        return self.store.path

    def __enter__(self) -> "Session":
        self._entered = True
        self.store.append(
            EventType.SESSION_START,
            {"name": self.name, "pid": os.getpid()},
        )
        recorder.install(self.store)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self.store.append(EventType.SESSION_END, {"status": "ok"})
            else:
                self.store.append(
                    EventType.SESSION_END,
                    {"status": "error", "error": f"{exc_type.__name__}: {exc}"},
                )
        except Exception:
            pass
        finally:
            recorder.uninstall()
        return False


def _disabled() -> bool:
    return os.environ.get("BIKEM_DISABLE", "").strip() in ("1", "true", "yes")


@contextlib.contextmanager
def session(name: str = "", root: Path | str | None = None) -> Iterator[Session]:
    """Open a bikem session. Everything recorded until exit."""
    if _disabled():
        yield Session(name=name, store=_NullStore())
        return

    store = SessionStore(root=root)
    sess = Session(name=name, store=store)
    with sess:
        yield sess


class _NullStore:
    """A store that does nothing. Used when BIKEM_DISABLE is set."""

    session_id = "sess_disabled"
    path = Path("/dev/null")

    def append(self, *a, **kw):
        from .events import Event, now_iso

        return Event(seq=0, type="disabled", session_id="sess_disabled", payload={}, ts=now_iso())

    def read(self):
        return []
