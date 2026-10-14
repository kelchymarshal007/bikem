from pathlib import Path

import httpx
import pytest

from bikem import recorder
from bikem.store import SessionStore


@pytest.fixture(autouse=True)
def cleanup():
    yield
    recorder.uninstall()


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(session_id="sess_rec", root=tmp_path)


def test_records_openai_style_call(tmp_path: Path):
    store = _store(tmp_path)
    recorder.install(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        r = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200

    events = store.read()
    types = [e.type for e in events]
    assert "llm.request" in types
    assert "llm.response" in types

    req = next(e for e in events if e.type == "llm.request")
    assert req.payload["model"] == "gpt-4o"
    assert req.payload["host"] == "api.openai.com"

    resp = next(e for e in events if e.type == "llm.response")
    assert resp.payload["status"] == 200
    assert resp.payload["body"]["choices"][0]["message"]["content"] == "hi"


@pytest.mark.asyncio
async def test_records_async_call(tmp_path: Path):
    store = _store(tmp_path)
    recorder.install(store)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"text": "hello"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": "claude-3-5-sonnet", "messages": []},
        )
    assert r.status_code == 200

    events = store.read()
    req = next(e for e in events if e.type == "llm.request")
    assert req.payload["host"] == "api.anthropic.com"
    assert req.payload["model"] == "claude-3-5-sonnet"


def test_ignores_non_llm_hosts(tmp_path: Path):
    store = _store(tmp_path)
    recorder.install(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client.post("https://example.com/whatever", json={"x": 1})
        client.get("https://api.openai.com/v1/models")

    assert store.read() == []


def test_records_error(tmp_path: Path):
    store = _store(tmp_path)
    recorder.install(store)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ConnectError):
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": []},
            )

    types = [e.type for e in store.read()]
    assert "llm.request" in types
    assert "error" in types


def test_recorder_failure_does_not_break_call(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    recorder.install(store)

    def boom(*a, **kw):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(store, "append", boom)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        r = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o", "messages": []},
        )
    assert r.status_code == 200


def test_uninstall_restores_httpx(tmp_path: Path):
    store = _store(tmp_path)
    original = httpx.Client.send
    recorder.install(store)
    assert httpx.Client.send is not original
    recorder.uninstall()
    assert httpx.Client.send is original
