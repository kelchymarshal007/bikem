"""Intercept httpx HTTP calls and record them as bikem events.

Patches httpx.Client.send and httpx.AsyncClient.send. Any SDK built on
httpx (OpenAI, Anthropic, Groq, Mistral, ...) is covered automatically.

Two invariants, non-negotiable:

1. Never break the host app. Every interception is best-effort.
2. Never consume a stream we do not own.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .events import EventType
from .store import SessionStore

_ORIGINAL_SYNC_SEND: Any = None
_ORIGINAL_ASYNC_SEND: Any = None
_ACTIVE_STORE: SessionStore | None = None

_LLM_HOSTS = (
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.cohere.ai",
    "api.mistral.ai",
    "api.groq.com",
    "api.together.xyz",
    "openrouter.ai",
    "api.deepseek.com",
    "api.perplexity.ai",
    "api.fireworks.ai",
    "api.replicate.com",
)

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")
_LOCAL_PATHS = ("/v1/chat", "/v1/completions", "/v1/messages", "/api/generate", "/api/chat")


def _should_record(request: httpx.Request) -> bool:
    if request.method.upper() != "POST":
        return False
    try:
        host = request.url.host or ""
    except Exception:
        return False
    if any(host == h or host.endswith("." + h) for h in _LLM_HOSTS):
        return True
    if host in _LOCAL_HOSTS:
        path = str(request.url.path or "")
        if any(p in path for p in _LOCAL_PATHS):
            return True
    return False


def _safe_json(body: bytes | None) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


def _summarize_request(request: httpx.Request) -> dict:
    try:
        raw = request.content if request.content is not None else None
    except Exception:
        raw = None
    parsed = _safe_json(raw if isinstance(raw, bytes) else None)
    model = parsed.get("model") if isinstance(parsed, dict) else None
    return {
        "method": request.method,
        "url": str(request.url),
        "host": request.url.host if request.url.host else None,
        "model": model,
        "body": parsed,
    }


def _summarize_response(response: httpx.Response) -> dict:
    info: dict[str, Any] = {"status": response.status_code}
    try:
        if not response.is_stream_consumed:
            info["streaming"] = True
            return info
        content = response.content
        parsed = _safe_json(content)
        info["body"] = parsed
    except Exception:
        pass
    return info


def _record(store: SessionStore | None, event_type: EventType, payload: dict) -> None:
    if store is None:
        return
    try:
        store.append(event_type, payload)
    except Exception:
        pass


async def _async_recording_send(self, request, **kwargs):
    store = _ACTIVE_STORE
    if store is None or not _should_record(request):
        return await _ORIGINAL_ASYNC_SEND(self, request, **kwargs)
    _record(store, EventType.LLM_REQUEST, _summarize_request(request))
    try:
        response = await _ORIGINAL_ASYNC_SEND(self, request, **kwargs)
    except Exception as exc:
        _record(store, EventType.ERROR, {"phase": "request", "error": str(exc)})
        raise
    _record(store, EventType.LLM_RESPONSE, _summarize_response(response))
    return response


def _sync_recording_send(self, request, **kwargs):
    store = _ACTIVE_STORE
    if store is None or not _should_record(request):
        return _ORIGINAL_SYNC_SEND(self, request, **kwargs)
    _record(store, EventType.LLM_REQUEST, _summarize_request(request))
    try:
        response = _ORIGINAL_SYNC_SEND(self, request, **kwargs)
    except Exception as exc:
        _record(store, EventType.ERROR, {"phase": "request", "error": str(exc)})
        raise
    _record(store, EventType.LLM_RESPONSE, _summarize_response(response))
    return response


def install(store: SessionStore) -> None:
    """Attach the recorder. Idempotent -- safe to call repeatedly."""
    global _ORIGINAL_SYNC_SEND, _ORIGINAL_ASYNC_SEND, _ACTIVE_STORE
    _ACTIVE_STORE = store
    if _ORIGINAL_SYNC_SEND is None:
        _ORIGINAL_SYNC_SEND = httpx.Client.send
        httpx.Client.send = _sync_recording_send
    if _ORIGINAL_ASYNC_SEND is None:
        _ORIGINAL_ASYNC_SEND = httpx.AsyncClient.send
        httpx.AsyncClient.send = _async_recording_send


def uninstall() -> None:
    """Detach the recorder and restore original httpx behavior.

    Also resets the module globals to None so a subsequent install() call
    will re-patch. Without this, install/uninstall cycles silently no-op.
    """
    global _ORIGINAL_SYNC_SEND, _ORIGINAL_ASYNC_SEND, _ACTIVE_STORE
    _ACTIVE_STORE = None
    if _ORIGINAL_SYNC_SEND is not None:
        httpx.Client.send = _ORIGINAL_SYNC_SEND
        _ORIGINAL_SYNC_SEND = None
    if _ORIGINAL_ASYNC_SEND is not None:
        httpx.AsyncClient.send = _ORIGINAL_ASYNC_SEND
        _ORIGINAL_ASYNC_SEND = None
