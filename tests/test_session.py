import httpx
import pytest

import bikem
from bikem import session
from bikem.events import EventType, verify_chain


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Redirect BIKEM_HOME to tmp_path so tests never touch the real ~/.bikem."""
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))
    monkeypatch.delenv("BIKEM_DISABLE", raising=False)
    yield


def test_session_records_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))
    with session("demo") as s:
        sid = s.session_id
        assert sid.startswith("sess_")
    events = bikem.load_session(sid, root=tmp_path)
    types = [e.type for e in events]
    assert EventType.SESSION_START.value in types
    assert EventType.SESSION_END.value in types
    ok, bad = verify_chain(events)
    assert ok and bad is None


def test_session_records_http_call(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    with session("with-http") as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": []},
            )

    events = bikem.load_session(s.session_id, root=tmp_path)
    types = [e.type for e in events]
    assert EventType.LLM_REQUEST.value in types
    assert EventType.LLM_RESPONSE.value in types


def test_session_records_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        with session("fails") as s:
            raise ValueError("boom")
    events = bikem.load_session(s.session_id, root=tmp_path)
    end = next(e for e in events if e.type == EventType.SESSION_END.value)
    assert end.payload["status"] == "error"
    assert "ValueError" in end.payload["error"]


def test_disable_env_makes_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))
    monkeypatch.setenv("BIKEM_DISABLE", "1")
    with session("noop") as s:
        assert s.session_id == "sess_disabled"
    sessions_dir = tmp_path / "sessions"
    if sessions_dir.exists():
        assert list(sessions_dir.glob("sess_*.jsonl")) == []


def test_recorder_uninstalled_after_session(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))
    original = httpx.Client.send
    with session("cleanup"):
        assert httpx.Client.send is not original
    assert httpx.Client.send is original
