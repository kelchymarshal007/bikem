"""A tiny mock agent that runs fully offline.

Uses httpx.MockTransport so no API key and no network calls are required.
Demonstrates what a bikem trace looks like for a healthy agent.

Run:
    python examples/mock_agent.py
    bikem list
    bikem play <session_id>
    bikem speak <session_id>
"""

from __future__ import annotations

import httpx

import bikem

# Canned LLM responses, one per API call.
REPLIES = [
    {"choices": [{"message": {"content": "I'll look up the current Bitcoin price."}}]},
    {"choices": [{"message": {"content": "The current price is 67,432 US dollars."}}]},
    {
        "choices": [
            {
                "message": {
                    "content": "Bitcoin is trading at 67,432 US dollars, up 2.1 percent today."
                }
            }
        ]
    },
]


def make_fake_llm():
    """Return a stateful fake LLM that serves REPLIES in order."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(state["i"], len(REPLIES) - 1)
        state["i"] += 1
        return httpx.Response(200, json=REPLIES[idx])

    return handler


def agent(question: str) -> str:
    """Three-step agent: plan, look up, summarize. Returns the final answer."""
    messages: list[dict] = [{"role": "user", "content": question}]

    with httpx.Client(transport=httpx.MockTransport(make_fake_llm())) as client:
        # Step 1 -- plan
        r1 = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
        messages.append(r1.json()["choices"][0]["message"])

        # Step 2 -- look up
        messages.append({"role": "user", "content": "What is the current price?"})
        r2 = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
        messages.append(r2.json()["choices"][0]["message"])

        # Step 3 -- summarize
        messages.append({"role": "user", "content": "Summarize for the user."})
        r3 = client.post(
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
        return r3.json()["choices"][0]["message"]["content"]


def main() -> None:
    with bikem.session("mock-agent") as s:
        answer = agent("What is the Bitcoin price?")
        print(f"\nAgent says: {answer}\n")

    print(f"Session ID : {s.session_id}")
    print(f"Trace file : {s.trace_path}")
    print()
    print("Try these next:")
    print("  bikem list")
    print(f"  bikem play {s.session_id}")
    print(f"  bikem speak {s.session_id}")


if __name__ == "__main__":
    main()
