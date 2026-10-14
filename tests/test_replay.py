from pathlib import Path

import httpx
import pytest

from bikem import replay, session
from bikem.replay import _request_fingerprint


def _record(tmp_path: Path, replies: list[dict]) -> str:
    """Record a session with N mock responses."""
    import os

    os.environ["BIKEM_HOME"] = str(tmp_path)
    it = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(it))

    with session("recording") as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for i in range(len(replies)):
                client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": f"msg {i}"}],
                    },
                )
    return s.session_id


def test_replay_returns_recorded_responses(tmp_path: Path):
    import os

    replies = [
        {"choices": [{"message": {"content": "first"}}]},
        {"choices": [{"message": {"content": "second"}}]},
    ]
    sid = _record(tmp_path, replies)
    os.environ["BIKEM_HOME"] = str(tmp_path)

    captured = []

    with replay(sid, root=tmp_path) as r:
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as client:
            for i in range(2):
                resp = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": f"msg {i}"}],
                    },
                )
                captured.append(resp.json())

    assert r.result.clean
    assert r.result.responses_replayed == 2
    assert captured[0]["choices"][0]["message"]["content"] == "first"
    assert captured[1]["choices"][0]["message"]["content"] == "second"


def test_replay_detects_request_mismatch(tmp_path: Path):
    import os

    sid = _record(tmp_path, [{"choices": [{"message": {"content": "ok"}}]}])
    os.environ["BIKEM_HOME"] = str(tmp_path)

    with replay(sid, root=tmp_path) as r:
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "DIFFERENT"}]},
            )

    assert not r.result.clean
    assert r.result.divergences[0].kind == "request_mismatch"


def test_replay_strict_raises_on_mismatch(tmp_path: Path):
    import os

    sid = _record(tmp_path, [{"choices": [{"message": {"content": "ok"}}]}])
    os.environ["BIKEM_HOME"] = str(tmp_path)

    with pytest.raises(RuntimeError):
        with replay(sid, root=tmp_path, strict=True):
            with httpx.Client(
                transport=httpx.MockTransport(lambda req: httpx.Response(500))
            ) as client:
                client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "DIFFERENT"}],
                    },
                )


def test_replay_detects_exhausted_trace(tmp_path: Path):
    import os

    sid = _record(tmp_path, [{"choices": [{"message": {"content": "only one"}}]}])
    os.environ["BIKEM_HOME"] = str(tmp_path)

    with replay(sid, root=tmp_path) as r:
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "msg 0"}]},
            )
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "msg 1"}]},
            )

    assert not r.result.clean
    assert any(d.kind == "exhausted" for d in r.result.divergences)


def test_replay_no_network_calls(tmp_path: Path):
    """Even though MockTransport would hit 500, replay must never reach it."""
    import os

    sid = _record(tmp_path, [{"choices": [{"message": {"content": "from trace"}}]}])
    os.environ["BIKEM_HOME"] = str(tmp_path)

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"error": "should not happen"})

    with replay(sid, root=tmp_path):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            r = client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "msg 0"}]},
            )

    assert calls == []
    assert r.status_code == 200


def test_replay_uninstalls_on_exit(tmp_path: Path):
    import os

    sid = _record(tmp_path, [{"choices": [{"message": {"content": "ok"}}]}])
    os.environ["BIKEM_HOME"] = str(tmp_path)
    original = httpx.Client.send

    with replay(sid, root=tmp_path):
        assert httpx.Client.send is not original

    assert httpx.Client.send is original


def test_fingerprint_ignores_irrelevant_fields():
    a = {"body": {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}}
    b = {
        "body": {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "user_metadata": {"trace_id": "xyz"},
            "request_id": "abc",
        }
    }
    assert _request_fingerprint(a) == _request_fingerprint(b)


def test_replay_missing_session_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        replay("sess_doesnotexist", root=tmp_path)
