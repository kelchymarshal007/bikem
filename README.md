# bikem

Local-first memory and drift detection for long AI sessions.

    import bikem

    with bikem.session("fix-auth-bug"):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "explain this stack trace"}],
        )
    # every call is now recorded to ~/.bikem/sessions/

Long AI sessions forget. They drift. They repeat. When something breaks at
step 40, you cannot reproduce it because the model is non-deterministic.
bikem records every LLM and tool call to a local JSONL file, reinjects the
right context so the session stops degrading, and flags the moment output
starts drifting from the original task.

No account. No network calls to us. Your traces are files on your disk.

## Install

    pip install bikem

## Commands

| Command | What it does |
|---|---|
| `bikem list` | Show recent sessions |
| `bikem show <id>` | Print the trace as events |
| `bikem play <id>` | Animate a session like a video |
| `bikem speak <id>` | Narrate a session aloud |
| `bikem diff <id1> <id2>` | Find the first divergence between two runs |
| `bikem verify <id>` | Check hash chain integrity |
| `bikem path <id>` | Print the raw JSONL file path |
| `bikem stats` | Summary across all sessions |
| `bikem last` | Print the most recent session id |
| `bikem voices` | List available TTS voices |

Every command accepts `last`, `prev`, or `last~N` in place of a session id, and `play`, `show`, `speak`, `diff` work with no arguments at all — they default to the most recent session(s).

Run `bikem <command> --help` for full options.

## Documentation

- [Quickstart](docs/quickstart.md) — install to first trace in under two minutes
- [Commands](docs/commands.md) — every command, flag, and example
- [Troubleshooting](docs/troubleshooting.md) — symptom to fix

## Status

Alpha. Recorder and store are being built now.

## License

MIT
