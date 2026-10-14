"""Explicit tool-call recording.

Mark a function with @bikem.tool() and every call gets written to the
active session as a tool.call, every return as a tool.result, and every
raised exception as an error.

Outside a session, the decorator is a no-op -- zero overhead.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any, TypeVar

from . import recorder
from .events import EventType

F = TypeVar("F", bound=Callable[..., Any])


def _safe(obj: Any) -> Any:
    try:
        json.dumps(obj, default=str)
        return obj
    except Exception:
        return repr(obj)


def tool(name: str | None = None):
    """Record calls to this function as tool.call / tool.result events."""

    def decorator(fn: F) -> F:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            store = recorder._ACTIVE_STORE
            if store is None:
                return fn(*args, **kwargs)

            try:
                store.append(
                    EventType.TOOL_CALL,
                    {"name": tool_name, "args": _safe(list(args)), "kwargs": _safe(kwargs)},
                )
            except Exception:
                pass

            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                try:
                    store.append(
                        EventType.ERROR,
                        {"phase": "tool", "name": tool_name, "error": str(exc)},
                    )
                except Exception:
                    pass
                raise

            try:
                store.append(
                    EventType.TOOL_RESULT,
                    {"name": tool_name, "result": _safe(result)},
                )
            except Exception:
                pass

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
