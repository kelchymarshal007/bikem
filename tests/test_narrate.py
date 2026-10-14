from bikem.events import EventType, make_event
from bikem.narrate import narrate


def _session(events_spec):
    """Build a small session from a spec list of (type, payload)."""
    out = []
    prev = "0" * 64
    for i, (t, p) in enumerate(events_spec, 1):
        ev = make_event(i, t, "sess_x", p, prev_hash=prev)
        out.append(ev)
        prev = ev.hash
    return out


def test_empty_session():
    assert "Empty" in narrate([])


def test_start_and_end_only():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "noop", "pid": 1}),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "noop" in text
    assert "nothing" in text.lower() or "start and end" in text.lower()


def test_single_request_single_response():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "demo", "pid": 1}),
            (
                EventType.LLM_REQUEST,
                {"model": "gpt-4o", "body": {"messages": [{"role": "user", "content": "hi"}]}},
            ),
            (
                EventType.LLM_RESPONSE,
                {"status": 200, "body": {"choices": [{"message": {"content": "hello there"}}]}},
            ),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "demo" in text
    assert "gpt-4o" in text
    assert "1 message" in text
    assert "hello there" in text
    assert "cleanly" in text.lower()


def test_multiple_requests():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "multi", "pid": 1}),
            (
                EventType.LLM_REQUEST,
                {"model": "gpt-4o", "body": {"messages": [{"role": "user", "content": "a"}]}},
            ),
            (
                EventType.LLM_RESPONSE,
                {"status": 200, "body": {"choices": [{"message": {"content": "1"}}]}},
            ),
            (
                EventType.LLM_REQUEST,
                {"model": "gpt-4o", "body": {"messages": [{"role": "user", "content": "b"}]}},
            ),
            (
                EventType.LLM_RESPONSE,
                {"status": 200, "body": {"choices": [{"message": {"content": "2"}}]}},
            ),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "2 requests" in text


def test_with_tool_call():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "tools", "pid": 1}),
            (EventType.TOOL_CALL, {"name": "search_web"}),
            (EventType.TOOL_RESULT, {"output": "found 3 results"}),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "search_web" in text


def test_with_error():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "erry", "pid": 1}),
            (EventType.ERROR, {"error": "connection refused"}),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "connection refused" in text
    assert "error" in text.lower()


def test_with_drift():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "drift", "pid": 1}),
            (EventType.DRIFT_FLAG, {"reason": "constraint violated"}),
            (EventType.SESSION_END, {"status": "ok"}),
        ]
    )
    text = narrate(events)
    assert "drift" in text.lower()
    assert "constraint violated" in text


def test_error_status_end():
    events = _session(
        [
            (EventType.SESSION_START, {"name": "boom", "pid": 1}),
            (EventType.SESSION_END, {"status": "error", "error": "ValueError: bad input"}),
        ]
    )
    text = narrate(events)
    assert "ValueError" in text


def test_narrate_never_raises_on_missing_fields():
    events = _session(
        [
            (EventType.SESSION_START, {}),
            (EventType.LLM_REQUEST, {}),
            (EventType.LLM_RESPONSE, {}),
            (EventType.SESSION_END, {}),
        ]
    )
    text = narrate(events)
    assert isinstance(text, str)
    assert len(text) > 0
