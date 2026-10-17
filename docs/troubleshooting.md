# Troubleshooting

Symptom to cause to fix. Search this page for your error message.

---

## "No sessions recorded yet"

**Cause:** You have not run any code inside `bikem.session()` yet, or you are looking at a different storage location.

**Fix:** Either run something inside a session, or check where your sessions are:

~~~bash
echo $BIKEM_HOME
ls ~/.bikem/sessions/
~~~

If `BIKEM_HOME` is set, sessions go there instead of `~/.bikem`.

---

## Session records nothing — `list` shows 0 events

**Cause:** The LLM SDK you are using does not sit on top of `httpx`. bikem intercepts at the httpx transport layer, which covers OpenAI, Anthropic, Groq, Mistral, Together, and any OpenAI-compatible endpoint. It does not cover SDKs that use `requests`, `aiohttp`, or `urllib` directly.

**Fix:** Check your SDK's HTTP layer. If it uses `httpx`, bikem sees it. If it uses `requests`, either switch SDKs or file an issue — bikem could add a second interceptor.

---

## Streaming responses show `streaming: true` with no content

**Cause:** This is correct behavior. When a response is streamed and the caller consumes it lazily, bikem records the status and the fact that it streamed, but does not read the body — reading it would break the caller.

**Fix:** Nothing. If you need the streamed content in the trace, consume it in your own code and log the result with `@bikem.tool()`.

---

## `bikem play` crashes with `NameError: name 'time' is not defined`

**Cause:** Very old version.

**Fix:** Upgrade:

~~~bash
pip install --upgrade bikem
~~~

If you installed 0.1.0, this bug exists in it. Fixed in 0.1.1.

---

## "No such file or directory: session-id"

**Cause:** You typed a placeholder literally. Commands take real session ids, not `<session-id>`.

**Fix:** Use a keyword instead:

~~~bash
bikem play            # latest
bikem play last~1     # previous
~~~

Or copy the id from `bikem list`.

---

## `diff` shows divergences for two runs of the same code

**Cause (mock backend):** Non-deterministic mocks or clock-dependent code.

**Cause (real LLM):** This is expected. Real LLMs are non-deterministic. Even with `temperature=0` they vary slightly between runs. Two identical-looking runs will diverge at the response events.

**Fix (mock):** Nothing — investigate the divergence; it usually points to something real.

**Fix (real):** Nothing. This is what bikem was built to show. The value is having an immutable record of each specific run, not forcing runs to match.

---

## Voice says only the first letter or clips the last word

**Cause:** SAPI on Windows clips the last word of long utterances when called through WSL interop, and cold-starts cost 2–3 seconds per sentence if you launch a new process for each.

**Fix:** Upgrade to bikem 0.1.2 or later. The `_say_powershell` function now speaks all sentences in a single PowerShell process using `-EncodedCommand`, which avoids both the cold-start cost and the clipping.

---

## `pip install bikem` fails on Windows with `WinError 2` on `bikem.exe`

**Cause:** Windows pip cannot rename `bikem.exe` because another process holds a lock on the file. Usually VS Code or a stray Python process.

**Fix:**

~~~powershell
Get-Process python* | Stop-Process -Force
pip install --upgrade --force-reinstall --no-cache-dir bikem
~~~

If that still fails, use the module form instead — it always works:

~~~powershell
python -m bikem.cli.main --help
python -m bikem.cli.main play
~~~

The `.exe` wrapper is a convenience, not a requirement.

---

## `externally-managed-environment` error on Linux

**Cause:** Modern Debian/Ubuntu Pythons refuse system-wide installs.

**Fix:** Use a virtual environment:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install bikem
~~~

Or use `uv`:

~~~bash
uv venv
source .venv/bin/activate
uv pip install bikem
~~~

---

## "TTS not available"

**Cause:** No text-to-speech engine on this machine.

**Fix by platform:**

| Platform | Fix |
|---|---|
| Ubuntu/Debian | `sudo apt install espeak-ng` |
| Fedora | `sudo dnf install espeak-ng` |
| macOS | Built in — should always work |
| WSL | Should auto-detect Windows SAPI. If not, run inside Windows PowerShell instead |
| Windows | Built in |

To confirm which backend bikem sees:

~~~bash
bikem play --speak 2>&1 | head -1
~~~

The header shows `voice: <backend>` if one was found.

---

## `bikem diff` exits with code 2 in CI

**Cause:** That is intentional — `diff` exits 2 when it finds a divergence so CI can fail.

**Fix:** If you do not want CI to fail, invert the logic:

~~~bash
bikem diff last~1 last || true    # ignore divergence
~~~

Or capture the result:

~~~bash
if bikem diff last~1 last > /dev/null 2>&1; then
    echo "behavior unchanged"
else
    echo "behavior changed"
    exit 1
fi
~~~

---

## `@bikem.tool()` records nothing

**Cause:** The decorated function was called outside a `bikem.session()` block. Outside a session, the decorator is a no-op by design — zero overhead.

**Fix:** Wrap the calling code:

~~~python
with bikem.session("run"):
    result = my_tool(args)
~~~

---

## Traces are growing too large

**Cause:** Large payloads (file contents, long conversations) accumulate.

**Fix options:**

1. Turn recording off for a specific run:
   ~~~bash
   BIKEM_DISABLE=1 python my_script.py
   ~~~

2. Delete old sessions:
   ~~~bash
   rm ~/.bikem/sessions/sess_oldid.jsonl
   ~~~

3. Point `BIKEM_HOME` at a directory you can manage:
   ~~~bash
   export BIKEM_HOME=/var/log/bikem
   ~~~

There is currently no automatic retention policy. If you need one, file an issue.

---

## Getting more detail

Every command has `--help`:

~~~bash
bikem --help
bikem play --help
bikem diff --help
~~~

For bug reports, include:

1. `pip show bikem` output (version)
2. `python --version`
3. The exact command you ran
4. The full output, including the traceback
