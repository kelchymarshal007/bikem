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

## Status

Alpha. Recorder and store are being built now.

## License

MIT
