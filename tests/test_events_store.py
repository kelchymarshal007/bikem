import json
from pathlib import Path

from bikem.events import (
    GENESIS_HASH,
    EventType,
    canonical_json,
    make_event,
    verify_chain,
)
from bikem.store import SessionStore, list_sessions, load_session


def test_canonical_json_is_stable():
    a = {"b": 2, "a": 1, "c": [3, 2, 1]}
    b = {"c": [3, 2, 1], "a": 1, "b": 2}
    assert canonical_json(a) == canonical_json(b)


def test_hash_chain_links():
    e1 = make_event(1, EventType.SESSION_START, "sess_x", {"name": "t"})
    e2 = make_event(2, EventType.LLM_REQUEST, "sess_x", {"model": "gpt-4o"}, prev_hash=e1.hash)
    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.hash
    ok, bad = verify_chain([e1, e2])
    assert ok and bad is None


def test_hash_chain_detects_tampering():
    e1 = make_event(1, EventType.SESSION_START, "sess_x", {"name": "t"})
    e2 = make_event(2, EventType.LLM_REQUEST, "sess_x", {"model": "gpt-4o"}, prev_hash=e1.hash)
    e2.payload["model"] = "gpt-4o-mini"
    ok, bad = verify_chain([e1, e2])
    assert not ok
    assert bad == 2


def test_store_append_and_read(tmp_path: Path):
    store = SessionStore(session_id="sess_test", root=tmp_path)
    store.append(EventType.SESSION_START, {"name": "demo"})
    store.append(EventType.LLM_REQUEST, {"model": "gpt-4o"})
    store.append(EventType.SESSION_END, {"status": "ok"})
    events = load_session("sess_test", root=tmp_path)
    assert len(events) == 3
    assert [e.seq for e in events] == [1, 2, 3]
    ok, bad = verify_chain(events)
    assert ok and bad is None


def test_store_survives_write_failure(tmp_path: Path, monkeypatch):
    store = SessionStore(session_id="sess_x", root=tmp_path)

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", boom)
    store.append(EventType.SESSION_START, {"name": "x"})


def test_list_sessions(tmp_path: Path):
    SessionStore(session_id="sess_a", root=tmp_path).append(EventType.SESSION_START, {})
    SessionStore(session_id="sess_b", root=tmp_path).append(EventType.SESSION_START, {})
    ids = {s["session_id"] for s in list_sessions(root=tmp_path)}
    assert ids == {"sess_a", "sess_b"}


def test_jsonl_roundtrip(tmp_path: Path):
    store = SessionStore(session_id="sess_r", root=tmp_path)
    ev = store.append(EventType.LLM_RESPONSE, {"text": "hello", "tokens": 3})
    raw = (tmp_path / "sessions" / "sess_r.jsonl").read_text().strip()
    parsed = json.loads(raw)
    assert parsed["hash"] == ev.hash
    assert parsed["payload"]["text"] == "hello"
