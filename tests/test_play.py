import os
from pathlib import Path

import httpx
from click.testing import CliRunner

from bikem import session
from bikem.cli.main import main


def _make_session(root: Path, name: str = "play-demo") -> str:
    os.environ["BIKEM_HOME"] = str(root)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with session(name) as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )
    return s.session_id


def test_play_renders_header_and_events(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["play", sid, "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 0
    assert sid in r.output
    assert "play-demo" in r.output
    assert "session.start" in r.output
    assert "llm.request" in r.output
    assert "llm.response" in r.output
    assert "session.end" in r.output
    assert "clean" in r.output


def test_play_shows_model_and_message_count(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["play", sid, "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 0
    assert "gpt-4o" in r.output
    assert "1 msg" in r.output


def test_play_missing_session(tmp_path: Path):
    r = CliRunner().invoke(main, ["play", "nope", "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 1


def test_play_shows_drift_when_present(tmp_path: Path):
    sid = _make_session(tmp_path)
    # Append a drift flag manually
    from bikem.events import EventType
    from bikem.store import SessionStore

    store = SessionStore(session_id=sid, root=tmp_path)
    events = store.read()
    store._seq = events[-1].seq
    store._last_hash = events[-1].hash
    store.append(EventType.DRIFT_FLAG, {"reason": "constraint violated"})

    r = CliRunner().invoke(main, ["play", sid, "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 0
    assert "drift" in r.output.lower()
