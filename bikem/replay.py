"""Deterministic replay from a recorded bikem trace.

Replay re-executes the caller's code path and substitutes recorded LLM
responses for real API calls. The result is deterministic: same inputs,
same outputs, zero network, zero cost.

Divergence is detected by comparing a canonical hash of each live request
against the corresponding recorded request. Any mismatch is reported but
does not stop replay by default -- the caller decides what to do.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from .events import Event, EventType, canonical_json, compute_hash
from .store import SessionStore, load_session


@dataclass
class Divergence:
    """A point where replay deviated from the recorded trace."""

    seq: int
    kind: str  # "request_mismatch" | "extra_request" | "exhausted"
    detail: str
    recorded_hash: str | None = None
    live_hash: str | None = None


@dataclass
class ReplayResult:
    """What happened during replay."""

    session_id: str
    requests_replayed: int = 0
    responses_replayed: int = 0
    divergences: list[Divergence] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.divergences


def _request_fingerprint(payload: dict) -> str:
    """Canonical hash of the meaningful parts of an LLM request.

    Only the fields that affect the model's response are included. Transport
    noise (headers, URL ordering, user-agent) is deliberately excluded --
    otherwise replay would report false divergence on every run.
    """
    body = payload.get("body") or {}
    if not isinstance(body, dict):
        body = {}
    # Keep the fields that change model output. Everything else is noise.
    meaningful = {
        "model": body.get("model"),
        "messages": body.get("messages"),
        "tools": body.get("tools"),
        "tool_choice": body.get("tool_choice"),
        "temperature": body.get("temperature"),
        "top_p": body.get("top_p"),
        "max_tokens": body.get("max_tokens") or body.get("max_output_tokens"),
        "stop": body.get("stop"),
        "system": body.get("system"),
    }
    return compute_hash("", meaningful)


def _build_httpx_response(recorded: dict, request: httpx.Request) -> httpx.Response:
    """Construct a synthetic httpx.Response carrying the recorded body."""
    status = recorded.get("status", 200)
    body = recorded.get("body")
    if body is None:
        return httpx.Response(status, request=request)
    try:
        content = json.dumps(body).encode("utf-8")
    except Exception:
        content = b""
    return httpx.Response(
        status,
        content=content,
        headers={"content-type": "application/json"},
        request=request,
    )


class Replayer:
    """Replays a recorded session. One instance per replay run."""

    def __init__(self, session_id: str, root: Any = None, strict: bool = False):
        self.session_id = session_id
        self.strict = strict
        self.result = ReplayResult(session_id=session_id)

        events = load_session(session_id, root=root)
        if not events:
            raise ValueError(f"No events found for session {session_id!r}")

        # Build ordered lists of request/response pairs by walking seq order.
        self._pairs: list[tuple[Event, Event | None]] = []
        pending_request: Event | None = None
        for ev in events:
            if ev.type == EventType.LLM_REQUEST.value:
                if pending_request is not None:
                    # A previous request never got a response -- record it.
                    self._pairs.append((pending_request, None))
                pending_request = ev
            elif ev.type == EventType.LLM_RESPONSE.value:
                if pending_request is not None:
                    self._pairs.append((pending_request, ev))
                    pending_request = None
        if pending_request is not None:
            self._pairs.append((pending_request, None))

        self._cursor = 0

    @property
    def total_pairs(self) -> int:
        return len(self._pairs)

    def next_response(self, live_request: httpx.Request) -> httpx.Response:
        """Return the recorded response for the current cursor.

        Compares the live request against the recorded one. On mismatch,
        records a divergence. Advances the cursor regardless.
        """
        if self._cursor >= len(self._pairs):
            self.result.divergences.append(
                Divergence(
                    seq=-1,
                    kind="exhausted",
                    detail=f"more requests than recorded ({self._cursor + 1} > {len(self._pairs)})",
                )
            )
            # Return a synthetic empty response so replay can continue
            # rather than crashing the caller's code.
            return httpx.Response(599, content=b"", request=live_request)

        recorded_request, recorded_response = self._pairs[self._cursor]
        self._cursor += 1
        self.result.requests_replayed += 1

        # Fingerprint comparison.
        try:
            live_body = json.loads(live_request.content) if live_request.content else {}
        except Exception:
            live_body = {}
        live_payload = {"body": live_body}
        live_hash = _request_fingerprint(live_payload)
        recorded_hash = _request_fingerprint(recorded_request.payload or {})

        if live_hash != recorded_hash:
            self.result.divergences.append(
                Divergence(
                    seq=recorded_request.seq,
                    kind="request_mismatch",
                    detail=(
                        f"request at cursor {self._cursor} differs from recorded "
                        f"(seq {recorded_request.seq})"
                    ),
                    recorded_hash=recorded_hash,
                    live_hash=live_hash,
                )
            )
            if self.strict:
                raise RuntimeError(
                    f"ReplayDivergence at seq {recorded_request.seq}: "
                    "request body differs from recorded trace"
                )

        if recorded_response is None:
            # No response was recorded -- likely the original call errored.
            return httpx.Response(599, content=b"", request=live_request)

        self.result.responses_replayed += 1
        return _build_httpx_response(recorded_response.payload or {}, live_request)


# ---------------------------------------------------------------------------
# Monkey-patching for the replay context
# ---------------------------------------------------------------------------

_ORIGINAL_SYNC_SEND: Any = None
_ORIGINAL_ASYNC_SEND: Any = None
_ACTIVE_REPLAYER: Replayer | None = None


def _should_intercept(request: httpx.Request) -> bool:
    from .recorder import _should_record

    return _should_record(request)


def _sync_replay_send(self, request, **kwargs):
    if _ACTIVE_REPLAYER is None or not _should_intercept(request):
        return _ORIGINAL_SYNC_SEND(self, request, **kwargs)
    return _ACTIVE_REPLAYER.next_response(request)


async def _async_replay_send(self, request, **kwargs):
    if _ACTIVE_REPLAYER is None or not _should_intercept(request):
        return await _ORIGINAL_ASYNC_SEND(self, request, **kwargs)
    return _ACTIVE_REPLAYER.next_response(request)


def install(replayer: Replayer) -> None:
    """Attach replay interception. Idempotent."""
    global _ORIGINAL_SYNC_SEND, _ORIGINAL_ASYNC_SEND, _ACTIVE_REPLAYER
    _ACTIVE_REPLAYER = replayer
    if _ORIGINAL_SYNC_SEND is None:
        _ORIGINAL_SYNC_SEND = httpx.Client.send
        httpx.Client.send = _sync_replay_send
    if _ORIGINAL_ASYNC_SEND is None:
        _ORIGINAL_ASYNC_SEND = httpx.AsyncClient.send
        httpx.AsyncClient.send = _async_replay_send


def uninstall() -> None:
    """Detach replay interception and reset globals."""
    global _ORIGINAL_SYNC_SEND, _ORIGINAL_ASYNC_SEND, _ACTIVE_REPLAYER
    _ACTIVE_REPLAYER = None
    if _ORIGINAL_SYNC_SEND is not None:
        httpx.Client.send = _ORIGINAL_SYNC_SEND
        _ORIGINAL_SYNC_SEND = None
    if _ORIGINAL_ASYNC_SEND is not None:
        httpx.AsyncClient.send = _ORIGINAL_ASYNC_SEND
        _ORIGINAL_ASYNC_SEND = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class ReplayContext:
    """Returned by bikem.replay(). Use .result after the block exits."""

    def __init__(self, replayer: Replayer):
        self._replayer = replayer

    @property
    def result(self) -> ReplayResult:
        return self._replayer.result

    def __enter__(self) -> "ReplayContext":
        install(self._replayer)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        uninstall()
        return False


def replay(session_id: str, root: Any = None, strict: bool = False) -> ReplayContext:
    """Replay a recorded session deterministically.

    Usage:

        with bikem.replay("sess_abc") as r:
            run_my_agent()   # same code as before, no API calls
        if not r.result.clean:
            print(r.result.divergences)
    """
    return ReplayContext(Replayer(session_id=session_id, root=root, strict=strict))
