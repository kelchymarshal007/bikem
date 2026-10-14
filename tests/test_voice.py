from bikem.events import EventType, make_event
from bikem.voice import Speaker, explain


def test_speaker_never_raises_with_no_backend():
    s = Speaker(enabled=False)
    assert not s.available
    s.say("this should do nothing")
    s.say("")
    s.say("a" * 1000)


def test_speaker_available_never_raises():
    # Whatever backend this environment has, say() must not raise.
    s = Speaker()
    s.say("test")


def test_explain_session_start():
    ev = make_event(1, EventType.SESSION_START, "sess_x", {"name": "demo"})
    assert "demo" in explain(ev).lower()


def test_explain_llm_request():
    ev = make_event(
        2,
        EventType.LLM_REQUEST,
        "sess_x",
        {
            "model": "gpt-4o",
            "body": {"messages": [{"role": "user", "content": "hi"}]},
        },
    )
    text = explain(ev)
    assert "gpt-4o" in text
    assert "1 message" in text


def test_explain_llm_response():
    ev = make_event(
        3,
        EventType.LLM_RESPONSE,
        "sess_x",
        {
            "status": 200,
            "body": {"choices": [{"message": {"content": "hello there"}}]},
        },
    )
    text = explain(ev)
    assert "hello there" in text
    assert "200" in text


def test_explain_drift():
    ev = make_event(4, EventType.DRIFT_FLAG, "sess_x", {"reason": "constraint violated"})
    assert "drift" in explain(ev).lower()
    assert "constraint violated" in explain(ev)


def test_explain_error():
    ev = make_event(5, EventType.ERROR, "sess_x", {"error": "connection refused"})
    assert "error" in explain(ev).lower()
    assert "connection refused" in explain(ev)


def test_explain_session_end_ok():
    ev = make_event(6, EventType.SESSION_END, "sess_x", {"status": "ok"})
    assert "cleanly" in explain(ev)


def test_explain_session_end_error():
    ev = make_event(7, EventType.SESSION_END, "sess_x", {"status": "error", "error": "boom"})
    assert "error" in explain(ev).lower()
    assert "boom" in explain(ev)
