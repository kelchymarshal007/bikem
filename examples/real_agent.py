"""A minimal real OpenAI agent. Requires OPENAI_API_KEY.

If the key isn't set, prints setup instructions instead of running.

Cost: about $0.0001 per run with gpt-4o-mini.

Run:
    export OPENAI_API_KEY=sk-...
    python examples/real_agent.py
    bikem play <session_id> --speak
"""

from __future__ import annotations

import os
import sys

import httpx

import bikem

API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"


def agent(prompt: str) -> str:
    api_key = os.environ["OPENAI_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.post(API_URL, headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set.")
        print()
        print("Set it and rerun:")
        print("  export OPENAI_API_KEY=sk-...")
        print("  python examples/real_agent.py")
        sys.exit(1)

    with bikem.session("real-agent") as s:
        answer = agent("In one sentence, what is HTTPX?")
        print(f"\nModel says: {answer}\n")

    print(f"Session ID : {s.session_id}")
    print(f"Trace file : {s.trace_path}")
    print()
    print("Try these next:")
    print(f"  bikem play {s.session_id}")
    print(f"  bikem speak {s.session_id}")


if __name__ == "__main__":
    main()
