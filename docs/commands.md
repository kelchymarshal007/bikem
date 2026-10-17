# Commands

Every command, every flag, every example.

Run `bikem <command> --help` at any time for the built-in help.

## Global behavior

Every command that takes a session id accepts these keywords instead of a literal id:

| Keyword | Meaning |
|---|---|
| `last` or `latest` | The most recent session |
| `prev` | The second most recent |
| `last~N` | N sessions back (0 = most recent) |

Prefix matching is supported: `bikem show 3f9a` resolves to the unique session whose id contains `3f9a`.

Set `BIKEM_HOME` to override the storage directory. Default is `~/.bikem`.

Set `BIKEM_DISABLE=1` to make `bikem.session()` a no-op.

Set `BIKEM_VOICE` to a TTS voice name to change the default voice.

---

## `bikem list`

Show recent sessions, newest first.

~~~bash
bikem list                    # default 20
bikem list -n 100             # show 100
bikem list --root /tmp/sess   # alternate storage location
~~~

Columns: session id, size on disk, modification time, event count.

---

## `bikem show <id>`

Print a session trace as a list of events.

~~~bash
bikem show                    # latest session
bikem show sess_abc123
bikem show last~2             # three sessions ago
bikem show --full             # include full payloads (JSON)
bikem show --type llm.request # only show LLM request events
~~~

Use `--full` when you need to see exactly what was sent to the model or what the tool returned.

---

## `bikem play <id>`

Animated playback. One event reveals at a time, like a video.

~~~bash
bikem play                    # latest session
bikem play --no-animate       # print all events instantly
bikem play --step             # press Enter to advance
bikem play --speed 2          # two times faster
bikem play --speak            # visual playback then spoken narration
bikem play --speak --voice "Microsoft Zira Desktop"
~~~

The header line shows session name, duration, event count, drift/error status, and the current TTS voice.

---

## `bikem speak <id>`

Speak the narration only. No visual output.

~~~bash
bikem speak                   # latest session
bikem speak sess_abc123
bikem speak last~1
bikem speak --rate 200        # words per minute
bikem speak --voice "Microsoft Zira Desktop"
~~~

On WSL, works through Windows SAPI. On Linux, requires `espeak-ng`. On macOS, uses `say`.

---

## `bikem diff <id1> <id2>`

Compare two sessions and report the first divergence.

~~~bash
bikem diff                    # compare two most recent
bikem diff last~1 last
bikem diff sess_a sess_b
bikem diff sess_a sess_b --full   # print full payloads side by side
~~~

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Sessions identical |
| 2 | Divergence detected |
| 1 | Error (missing session, bad arguments) |

Exit code 2 makes `bikem diff` safe to use in CI:

~~~bash
bikem diff last~1 last || echo "behavior changed"
~~~

Only behavior-bearing events are compared: LLM requests, LLM responses, tool calls, tool results, context injections, drift flags, errors. Session start and end are ignored so that two runs with different names register as identical.

---

## `bikem verify <id>`

Verify the hash chain integrity of a session.

~~~bash
bikem verify
bikem verify sess_abc123
~~~

Reports `OK` if the chain is intact, `BROKEN` with the first bad sequence number otherwise. Exit code 2 on break.

Use this to prove a trace has not been tampered with.

---

## `bikem path <id>`

Print the raw JSONL file path.

~~~bash
bikem path
bikem path last~3
~~~

Useful for `scp`, `git add`, or piping into `grep`/`jq`.

---

## `bikem stats`

Summary across all sessions.

~~~bash
bikem stats
~~~

Shows total session count, total event count, total disk usage, and a breakdown by event type.

---

## `bikem last`

Print the most recent session id. Pipeable.

~~~bash
bikem last                    # one id
bikem last -n 5               # five most recent
~~~

Typical use:

~~~bash
bikem play "$(bikem last)"
~~~

---

## `bikem voices`

List text-to-speech voices installed on this machine.

~~~bash
bikem voices
~~~

Shows voice names you can pass to `--voice`. On WSL typically includes `Microsoft Zira Desktop` (female) and `Microsoft David Desktop` (male).
