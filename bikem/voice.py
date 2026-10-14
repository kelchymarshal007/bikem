"""Text-to-speech for bikem playback.

Shells out to the operating system's TTS engine. No Python dependencies.
Backend is chosen once at Speaker construction:

    wsl-sapi   WSL2 calling Windows SAPI via powershell.exe  (best on WSL)
    macos      /usr/bin/say
    espeak-ng  Linux
    espeak     Linux fallback
    windows    native Windows PowerShell
    None       no TTS available; Speaker.say() is a no-op

A Speaker instance NEVER raises. If TTS breaks mid-session, it prints one
warning and goes silent. Playback must never crash because of audio.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .events import Event, EventType

_WSL_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


class Speaker:
    """Minimal TTS wrapper. Never raises."""

    def __init__(self, rate: int = 175, enabled: bool = True, voice: str | None = None):
        self.rate = rate
        # Fall back to BIKEM_VOICE env var if no explicit voice was given.
        self.voice = voice or os.environ.get("BIKEM_VOICE") or None
        self._backend: str | None = None
        self._warned = False
        if enabled:
            self._backend = self._detect()

    @property
    def available(self) -> bool:
        return self._backend is not None

    @property
    def backend(self) -> str:
        return self._backend or "none"

    def _detect(self) -> str | None:
        if Path(_WSL_POWERSHELL).exists():
            return "wsl-sapi"
        if _has("say"):
            return "macos"
        if _has("espeak-ng"):
            return "espeak-ng"
        if _has("espeak"):
            return "espeak"
        if sys.platform == "win32" and _has("powershell"):
            return "windows"
        return None

    def say(self, text: str) -> None:
        """Speak a paragraph. Never raises.

        Windows/WSL: one PowerShell process speaks all sentences inside
        a single Speak() loop -- no per-sentence relaunch, so no gap.
        macOS/Linux: one subprocess per sentence is cheap, no delay.
        """
        if not self._backend or not text:
            return
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        if not parts:
            parts = [text.strip()]
        try:
            if self._backend in ("wsl-sapi", "windows"):
                ps = _WSL_POWERSHELL if self._backend == "wsl-sapi" else "powershell"
                self._say_powershell(ps, parts)
            else:
                for part in parts:
                    self._say_one(part)
        except Exception:
            if not self._warned:
                print("[dim]bikem: TTS failed, continuing silently[/dim]")
                self._warned = True

    def _say_one(self, text: str) -> None:
        """Speak a single short utterance. Never raises."""
        if len(text) > 240:
            text = text[:237] + "..."
        try:
            if self._backend == "wsl-sapi":
                self._say_powershell(_WSL_POWERSHELL, text)
            elif self._backend == "windows":
                self._say_powershell("powershell", text)
            elif self._backend == "macos":
                subprocess.run(
                    ["say", "-r", str(self.rate), text],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            else:  # espeak-ng / espeak
                subprocess.run(
                    [self._backend, "-s", str(self.rate), text],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
        except Exception:
            if not self._warned:
                print("[dim]bikem: TTS failed, continuing silently[/dim]")
                self._warned = True

    def _say_powershell(self, ps_cmd: str, sentences: list[str]) -> None:
        """Speak a list of sentences in a single PowerShell process.

        One process launch, one .NET runtime boot, all Speak() calls in
        a loop. Avoids both the 2-3s cold-start cost per sentence AND
        the last-word clipping that plagues long single-utterance calls.
        """
        escaped = [s.replace("'", "''") for s in sentences]
        array_literal = ", ".join(f"'{s}'" for s in escaped)
        voice_line = ""
        if self.voice:
            voice_safe = self.voice.replace("'", "''")
            voice_line = f"try {{ $s.SelectVoice('{voice_safe}') }} catch {{}}; "
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 0; "
            + voice_line
            + f"$texts = @({array_literal}); "
            + "foreach ($t in $texts) { $s.Speak($t) }"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        subprocess.run(
            [ps_cmd, "-EncodedCommand", encoded],
            capture_output=True,
            timeout=180,
            check=False,
        )


def explain(ev: Event) -> str:
    """Plain-English sentence for one event. Template-based, no LLM."""
    p = ev.payload or {}
    t = ev.type

    if t == EventType.SESSION_START.value:
        return f"Session start. {p.get('name') or 'unnamed'}."

    if t == EventType.SESSION_END.value:
        status = p.get("status", "ok")
        if status == "ok":
            return "Session ended cleanly."
        return f"Session ended with error: {p.get('error') or 'unknown'}."

    if t == EventType.LLM_REQUEST.value:
        model = p.get("model") or "unknown model"
        body = p.get("body") or {}
        n = 0
        if isinstance(body, dict):
            n = len(body.get("messages") or [])
        return f"Request to {model}. {n} message{'s' if n != 1 else ''}."

    if t == EventType.LLM_RESPONSE.value:
        status = p.get("status")
        if p.get("streaming"):
            return f"Streaming response, status {status}."
        body = p.get("body") or {}
        snippet = ""
        if isinstance(body, dict):
            choices = body.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {}).get("content", "")
                if isinstance(msg, str):
                    snippet = msg[:140]
        if snippet:
            return f"Response status {status}. {snippet}"
        return f"Response status {status}."

    if t == EventType.TOOL_CALL.value:
        return f"Tool call: {p.get('name') or 'unknown'}."

    if t == EventType.TOOL_RESULT.value:
        return "Tool result received."

    if t == EventType.DRIFT_FLAG.value:
        return f"Drift detected. {p.get('reason') or 'unspecified'}."

    if t == EventType.ERROR.value:
        return f"Error. {p.get('error') or 'unknown'}."

    if t == EventType.CONTEXT_INJECT.value:
        return "Context injected."

    return t.replace(".", " ")


def list_voices() -> list[str]:
    """Return the names of available TTS voices. Empty list if none."""
    speaker = Speaker(enabled=True)
    if not speaker.available:
        return []
    try:
        if speaker.backend in ("wsl-sapi", "windows"):
            ps = _WSL_POWERSHELL if speaker.backend == "wsl-sapi" else "powershell"
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"
            )
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            result = subprocess.run(
                [ps, "-EncodedCommand", encoded],
                capture_output=True,
                timeout=10,
                check=False,
            )
            out = result.stdout.decode("utf-8", errors="ignore")
            return [ln.strip() for ln in out.splitlines() if ln.strip()]
        if speaker.backend == "macos":
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            out = result.stdout.decode("utf-8", errors="ignore")
            return [ln.split()[0] for ln in out.splitlines() if ln.strip()]
        # espeak / espeak-ng
        result = subprocess.run(
            [speaker.backend, "--voices"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        out = result.stdout.decode("utf-8", errors="ignore")
        names = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                names.append(parts[3])
        return names
    except Exception:
        return []
