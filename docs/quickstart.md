# Quickstart

Get from zero to a recorded trace in under two minutes.

## Install

~~~bash
pip install bikem
~~~

Requires Python 3.10+. Three runtime dependencies: `httpx`, `click`, `rich`. No account, no API key needed for bikem itself.

## Record your first session

Add two lines around any code that calls an LLM through httpx (OpenAI SDK, Anthropic SDK, Groq, Mistral, Ollama, and any other httpx-based client):

~~~python
import bikem

with bikem.session("my-first-run"):
    # your existing code, unchanged
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "say hi"}],
    )
~~~

When the `with` block exits, the trace is written to `~/.bikem/sessions/`. Nothing is sent anywhere. No network calls happen unless your own code makes them.

## Look at what was recorded

~~~bash
bikem list
~~~

You will see one row per session: id, size on disk, when it ran, how many events.

Play the most recent session — no arguments needed:

~~~bash
bikem play
~~~

Or a specific session:

~~~bash
bikem play sess_abc123def456
~~~

Or by keyword:

~~~bash
bikem play last        # most recent
bikem play last~1      # second most recent
bikem play prev        # same as last~1
~~~

## Hear the summary

~~~bash
bikem speak
~~~

Speaks a plain-English paragraph describing what happened. Uses the OS text-to-speech engine — no audio is uploaded.

On WSL this works out of the box via Windows SAPI. On Linux, install `espeak-ng`. On macOS, `say` is built in.

## Compare two runs

Run something twice, then:

~~~bash
bikem diff
~~~

Compares the two most recent sessions. Reports `identical` or the first event that diverged. Exits nonzero on divergence — safe to use in CI.

## What next

- `docs/commands.md` — every command and flag
- `docs/troubleshooting.md` — symptom to fix
- `examples/` — runnable scripts that show sessions, tools, and errors
