"""Event types, canonical serialization, and hash chain for bikem traces.

Every recorded action is an Event. Events form a hash chain: each event's
hash is computed over its own content plus the previous event's hash.
Tampering is detectable, and replay can verify consistency before trusting
a recorded response.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

GENESIS_HASH = "0" * 64


class EventType(str, Enum):
    """The only event types. Restraint is productivity."""

    SESSION_START = "session.start"
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    CONTEXT_INJECT = "context.inject"
    DRIFT_FLAG = "drift.flag"
    SESSION_END = "session.end"
    ERROR = "error"


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace variance.

    This is why replay can work at all. Two semantically identical payloads
    must serialize to byte-identical strings, or the hash chain breaks on
    every run and replay reports false divergence.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, body: dict) -> str:
    """sha256(prev_hash || canonical_json(body)).

    body must NOT include the hash field itself.
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\n")
    h.update(canonical_json(body).encode("utf-8"))
    return h.hexdigest()


def new_session_id() -> str:
    return "sess_" + uuid.uuid4().hex[:12]


def now_iso() -> str:
    """UTC timestamp, ISO 8601 with milliseconds."""
    t = time.time()
    ms = int((t - int(t)) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % ms


@dataclass
class Event:
    seq: int
    type: str
    session_id: str
    payload: dict
    parent_seq: int | None = None
    prev_hash: str = GENESIS_HASH
    hash: str = ""
    ts: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            seq=d["seq"],
            type=d["type"],
            session_id=d["session_id"],
            payload=d.get("payload", {}),
            parent_seq=d.get("parent_seq"),
            prev_hash=d.get("prev_hash", GENESIS_HASH),
            hash=d.get("hash", ""),
            ts=d.get("ts", ""),
        )


def make_event(
    seq: int,
    event_type: EventType | str,
    session_id: str,
    payload: dict,
    prev_hash: str = GENESIS_HASH,
    parent_seq: int | None = None,
) -> Event:
    """Build an event and compute its hash in one step."""
    type_str = event_type.value if isinstance(event_type, EventType) else event_type
    event = Event(
        seq=seq,
        type=type_str,
        session_id=session_id,
        payload=payload,
        parent_seq=parent_seq,
        prev_hash=prev_hash,
        hash="",
    )
    body = event.to_dict()
    body.pop("hash", None)
    event.hash = compute_hash(prev_hash, body)
    return event


def verify_chain(events: list[Event]) -> tuple[bool, int | None]:
    """Verify the hash chain. Returns (ok, first_bad_seq)."""
    prev = GENESIS_HASH
    for ev in events:
        body = ev.to_dict()
        body.pop("hash", None)
        expected = compute_hash(ev.prev_hash, body)
        if ev.prev_hash != prev or ev.hash != expected:
            return False, ev.seq
        prev = ev.hash
    return True, None
