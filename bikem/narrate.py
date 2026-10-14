"""Turn a trace into a natural-language summary.

Template-based on purpose. No LLM calls, no network, no API keys. The
structured data is already there -- this module just tells the story that
the events describe.

Design rule: the output reads like a person who looked at the trace and
is telling you what happened. Short sentences. Named models. No jargon.
"""

from __future__ import annotations

from datetime import datetime

from .events import Event, EventType


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    if n == 1:
        return f"1 {singular}"
    return f"{n} {plural or singular + 's'}"


def _snip(text: str, n: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


def narrate(events: list[Event]) -> str:
    """Return a 2-4 sentence English summary of a session."""
    if not events:
        return "Empty session. No events were recorded."

    start = next((e for e in events if e.type == EventType.SESSION_START.value), events[0])
    end = next((e for e in reversed(events) if e.type == EventType.SESSION_END.value), events[-1])

    name = (start.payload or {}).get("name") or "unnamed"
    base_ts = _parse_ts(start.ts)
    end_ts = _parse_ts(end.ts)
    duration = (end_ts - base_ts).total_seconds() if base_ts and end_ts else 0.0

    requests = [e for e in events if e.type == EventType.LLM_REQUEST.value]
    responses = [e for e in events if e.type == EventType.LLM_RESPONSE.value]
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL.value]
    errors = [e for e in events if e.type == EventType.ERROR.value]
    drifts = [e for e in events if e.type == EventType.DRIFT_FLAG.value]

    sentences: list[str] = []

    # ---- Sentence 1: framing ----
    opening = f'Session "{name}" ran for {duration:.2f} seconds'
    end_status = (end.payload or {}).get("status", "ok")
    has_content = bool(requests or tool_calls or errors or drifts)
    if not has_content and end_status == "ok":
        opening += " and captured nothing but the start and end markers."
        return opening
    opening += f" and captured {_plural(len(events), 'event')}."
    sentences.append(opening)

    # ---- Sentence 2: what the model was asked ----
    if requests:
        models: list[str] = []
        for r in requests:
            m = (r.payload or {}).get("model")
            if m and m not in models:
                models.append(m)
        model_phrase = (
            " and ".join(models)
            if len(models) <= 2
            else ", ".join(models[:-1]) + f", and {models[-1]}"
        )

        total_msgs = 0
        for r in requests:
            body = (r.payload or {}).get("body") or {}
            if isinstance(body, dict):
                total_msgs += len(body.get("messages") or [])

        if len(requests) == 1:
            s = f"One request went to {model_phrase}"
            if total_msgs:
                s += f" with {_plural(total_msgs, 'message')}"
            s += "."
        else:
            s = f"You made {_plural(len(requests), 'request')} to {model_phrase}"
            if total_msgs:
                s += f", sending {_plural(total_msgs, 'message')} in total"
            s += "."
        sentences.append(s)

    # ---- Sentence 3: what the model said ----
    if responses:
        if len(responses) == 1:
            r = responses[0]
            status = (r.payload or {}).get("status", 200)
            body = (r.payload or {}).get("body") or {}
            snippet = ""
            if isinstance(body, dict):
                choices = body.get("choices")
                if isinstance(choices, list) and choices:
                    msg = choices[0].get("message", {}).get("content", "")
                    if isinstance(msg, str) and msg:
                        snippet = _snip(msg)
            if status != 200:
                sentences.append(f"The model returned status {status}.")
            elif snippet:
                sentences.append(f'The model replied: "{snippet}".')
            else:
                sentences.append("The model replied with a response, no text content.")
        else:
            snippets: list[str] = []
            for r in responses:
                body = (r.payload or {}).get("body") or {}
                if isinstance(body, dict):
                    choices = body.get("choices")
                    if isinstance(choices, list) and choices:
                        msg = choices[0].get("message", {}).get("content", "")
                        if isinstance(msg, str) and msg:
                            snippets.append(_snip(msg, 80))
            ok_count = sum(1 for r in responses if (r.payload or {}).get("status") == 200)
            s = f"The model returned {_plural(ok_count, 'successful response')}."
            if snippets:
                joined = "; ".join(f'"{s}"' for s in snippets[:3])
                if len(snippets) > 3:
                    joined += f", and {len(snippets) - 3} more"
                s = f"The model replied {joined}."
            sentences.append(s)

    # ---- Sentence 4: tool usage ----
    if tool_calls:
        names: list[str] = []
        for t in tool_calls:
            n = (t.payload or {}).get("name")
            if n and n not in names:
                names.append(n)
        if len(names) == 1:
            sentences.append(f"One tool was called: {names[0]}.")
        else:
            listed = ", ".join(names)
            sentences.append(f"Tools called: {listed}.")

    # ---- Sentence 5: issues ----
    if errors:
        first_err = (errors[0].payload or {}).get("error") or "unknown error"
        if len(errors) == 1:
            sentences.append(f"There was 1 error: {_snip(first_err, 100)}.")
        else:
            sentences.append(
                f"There were {len(errors)} errors, the first being: {_snip(first_err, 100)}."
            )

    if drifts:
        first_drift = (drifts[0].payload or {}).get("reason") or "unspecified drift"
        if len(drifts) == 1:
            sentences.append(f"Drift was detected: {_snip(first_drift, 100)}.")
        else:
            sentences.append(f"{len(drifts)} drift flags fired during the session.")

    # ---- Sentence 6: closing verdict ----
    status = (end.payload or {}).get("status", "ok")
    if status == "ok" and not errors and not drifts:
        sentences.append("Session completed cleanly.")
    elif status == "ok":
        sentences.append("Session ended, but not without issues.")
    else:
        err = (end.payload or {}).get("error") or "unknown"
        sentences.append(f"Session ended with an error: {_snip(err, 100)}.")

    return " ".join(sentences)
