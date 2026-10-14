# bikem examples

Three runnable scripts, from fully offline to real API.

| File | API key? | Cost | What it shows |
|---|---|---|---|
| mock_agent.py | No | Free | A healthy 3-call session |
| failing_agent.py | No | Free | A session that errors partway |
| real_agent.py | Yes (OPENAI_API_KEY) | ~$0.0001 | A real OpenAI call |

## Run them

~~~bash
# Offline, no setup
python examples/mock_agent.py

# Offline, shows an error trace
python examples/failing_agent.py

# Real API (needs a key)
export OPENAI_API_KEY=sk-...
python examples/real_agent.py
~~~

## Look at what they recorded

Each script prints a session id when it finishes. Use it:

~~~bash
bikem list                          # all sessions, newest first
bikem show <session_id>             # full trace with payloads
bikem play <session_id>             # animated playback
bikem play <session_id> --speak     # playback + spoken narration
bikem speak <session_id>            # narration only
bikem verify <session_id>           # hash chain check
~~~

## Compare two runs

Run mock_agent.py twice, then:

~~~bash
bikem diff <id1> <id2>
~~~

Identical runs report `identical`. If you edit the script between runs,
`diff` points at the first event that changed.
