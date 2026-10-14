"""A mock agent that fails partway through.

The first LLM call succeeds. The second one raises httpx.ConnectError,
which bikem records as an error event, and the session ends with a
non-ok status.

This is what a failing session looks like in a bikem trace.

Run:
    python examples/failing_agent.py
    bikem list
    bikem play <session_id>
"""

from __future__ import annotations

import httpx

import bikem

SUCCESS = {"choices": [{"message": {"content": "Starting research."}}]}


def make_handler():
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["i"] += 1
        if state["i"] == 1:
            return httpx.Response(200, json=SUCCESS)
        # Second call fails -- simulate a network drop.
        raise httpx.ConnectError("connection refused by upstream", request=request)

    return handler


def agent(prompt: str) -> str:
    messages: list[dict] = [{"role": "user", "content": prompt}]

    with httpx.Client(transport=httpx.MockTransport(make_handler())) as client:
        # Step 1 -- succeeds
        r1 = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
        messages.append(r1.json()["choices"][0]["message"])

        # Step 2 -- fails
        messages.append({"role": "user", "content": "continue"})
        r2 = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
        return r2.json()["choices"][0]["message"]["content"]


def main() -> None:
    with bikem.session("failing-agent") as s:
        try:
            agent("Research something and fail halfway.")
        except Exception as exc:
            print(f"\nAgent failed: {exc}\n")
            raise

    print(f"Session ID : {s.session_id}")
    print(f"Trace file : {s.trace_path}")


if __name__ == "__main__":
    main()
