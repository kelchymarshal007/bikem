"""bikem command-line interface.

Commands:

    bikem list                  List recent sessions
    bikem show <id>             Pretty-print a session trace
    bikem play <id>             Animate a session like a video
    bikem diff <id1> <id2>      Compare two sessions, find first divergence
    bikem verify <id>           Verify hash chain integrity
    bikem path <id>             Print the raw JSONL file path
    bikem stats                 Summary across all sessions
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..diff import diff_sessions
from ..diff import summarize as diff_summarize
from ..events import Event, EventType, verify_chain
from ..narrate import narrate
from ..store import SessionStore, list_sessions, load_session
from ..voice import Speaker, list_voices

console = Console()
err_console = Console(stderr=True)

_TYPE_STYLE = {
    EventType.SESSION_START.value: "bold green",
    EventType.SESSION_END.value: "bold green",
    EventType.LLM_REQUEST.value: "cyan",
    EventType.LLM_RESPONSE.value: "bright_cyan",
    EventType.TOOL_CALL.value: "yellow",
    EventType.TOOL_RESULT.value: "bright_yellow",
    EventType.CONTEXT_INJECT.value: "magenta",
    EventType.DRIFT_FLAG.value: "bold red",
    EventType.ERROR.value: "bold red",
}

_ICONS = {
    EventType.SESSION_START.value: ("\u25b6", "bold green"),
    EventType.SESSION_END.value: ("\u25a0", "bold green"),
    EventType.LLM_REQUEST.value: ("\u2192", "cyan"),
    EventType.LLM_RESPONSE.value: ("\u2190", "bright_cyan"),
    EventType.TOOL_CALL.value: ("\u2699", "yellow"),
    EventType.TOOL_RESULT.value: ("\u2713", "bright_yellow"),
    EventType.CONTEXT_INJECT.value: ("\u2295", "magenta"),
    EventType.DRIFT_FLAG.value: ("\u26a0", "bold red"),
    EventType.ERROR.value: ("\u2717", "bold red"),
}


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f}TB"


def _shorten(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "..."


def _parse_ts(ts: str):
    if not ts:
        return None
    try:
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _payload_summary(ev: Event) -> str:
    p = ev.payload or {}
    t = ev.type
    if t == EventType.SESSION_START.value:
        return f'"{p.get("name") or "unnamed"}"'
    if t == EventType.SESSION_END.value:
        s = p.get("status", "ok")
        if s == "ok":
            return "ok"
        return f"{s} \u00b7 {p.get('error', '')}"
    if t == EventType.LLM_REQUEST.value:
        model = p.get("model") or "?"
        body = p.get("body") or {}
        n = 0
        if isinstance(body, dict):
            n = len(body.get("messages") or [])
        return f"{model} \u00b7 {n} msg" + ("s" if n != 1 else "")
    if t == EventType.LLM_RESPONSE.value:
        parts = [str(p.get("status", "?"))]
        if p.get("streaming"):
            parts.append("streaming")
        body = p.get("body") or {}
        if isinstance(body, dict):
            choices = body.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {}).get("content", "")
                if isinstance(msg, str) and msg:
                    parts.append(_shorten(msg, 50))
        return " \u00b7 ".join(parts)
    if t == EventType.TOOL_CALL.value:
        name = p.get("name", "?")
        args = p.get("args") or []
        kwargs = p.get("kwargs") or {}
        rendered = [_shorten(json.dumps(a, default=str), 20) for a in args] + [
            f"{k}={_shorten(json.dumps(v, default=str), 20)}" for k, v in kwargs.items()
        ]
        return f"{name}({_shorten(', '.join(rendered), 45)})"
    if t == EventType.TOOL_RESULT.value:
        name = p.get("name", "?")
        result = p.get("result")
        return f"{name} \u2192 {_shorten(json.dumps(result, default=str), 50)}"
    if t == EventType.ERROR.value:
        if p.get("phase") == "tool":
            return f"tool {p.get('name', '?')} raised: {_shorten(p.get('error', ''), 40)}"
        return str(p.get("error", ""))
    return _shorten(json.dumps(p, default=str), 60)


def _event_line(ev: Event, base_ts) -> Text:
    icon, style = _ICONS.get(ev.type, ("\u2022", "white"))
    offset = ""
    ev_ts = _parse_ts(ev.ts)
    if base_ts is not None and ev_ts is not None:
        delta = (ev_ts - base_ts).total_seconds()
        offset = f"{delta:+6.2f}s"

    t = Text()
    t.append("  ")
    t.append(icon, style=style)
    t.append("  ")
    t.append(f"#{ev.seq:<3}", style="dim")
    t.append(f"{offset:>8}  ", style="dim")
    t.append(f"{ev.type:<17}", style=style)
    t.append(" ")
    t.append(_payload_summary(ev))
    return t


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """bikem -- local-first memory and drift detection for long AI sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("list")
@click.option("-n", "--limit", default=20, show_default=True, help="Max sessions to show.")
@click.option("--root", default=None, help="Override BIKEM_HOME.")
def cmd_list(limit: int, root: str | None) -> None:
    """List recent sessions, newest first."""
    sessions = list_sessions(root=root)
    if not sessions:
        console.print("[dim]No sessions recorded yet.[/dim]")
        console.print("[dim]Run some code inside bikem.session() and try again.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Size", justify="right")
    table.add_column("Modified", style="dim")
    table.add_column("Events", justify="right")

    for s in sessions[:limit]:
        try:
            mtime = datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            mtime = "?"
        try:
            n = sum(1 for _ in SessionStore(session_id=s["session_id"], root=root).iter_events())
        except Exception:
            n = 0
        table.add_row(s["session_id"], _human_size(s["size"]), mtime, str(n))

    console.print(table)
    if len(sessions) > limit:
        console.print(f"[dim]... {len(sessions) - limit} more[/dim]")


def _resolve_id(session_id: str, root: str | None) -> str | None:
    """Resolve a session id, prefix, or keyword like 'last' / 'last~2'."""
    sessions = list_sessions(root=root)
    if not sessions:
        err_console.print("[yellow]No sessions recorded yet.[/yellow]")
        err_console.print("[dim]Run some code inside bikem.session() first.[/dim]")
        return None

    # Keywords: last, latest, prev, last~N, latest~N
    if session_id in ("last", "latest"):
        return sessions[0]["session_id"]
    if session_id == "prev":
        if len(sessions) < 2:
            err_console.print("[red]Only 1 session available; no previous.[/red]")
            return None
        return sessions[1]["session_id"]
    if "~" in session_id:
        head, _, tail = session_id.partition("~")
        if head in ("last", "latest"):
            try:
                n = int(tail)
            except ValueError:
                err_console.print(f"[red]Bad offset:[/red] {session_id}")
                return None
            if n < 0 or n >= len(sessions):
                err_console.print(
                    f"[red]Only {len(sessions)} session(s); asked for last~{n}.[/red]"
                )
                return None
            return sessions[n]["session_id"]

    known = {s["session_id"] for s in sessions}
    if session_id in known:
        return session_id
    matches = [sid for sid in known if sid.endswith(session_id) or session_id in sid]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        err_console.print(f"[red]Ambiguous:[/red] {', '.join(sorted(matches))}")
    return None


@main.command("show")
@click.argument("session_id", required=False)
@click.option("--root", default=None)
@click.option("--full", is_flag=True, help="Print full payload JSON for every event.")
@click.option("--type", "type_filter", default=None, help="Only show events of this type.")
def cmd_show(session_id: str | None, root: str | None, full: bool, type_filter: str | None) -> None:
    """Pretty-print a session trace. Defaults to the latest session."""
    session_id = session_id or "last"
    resolved = _resolve_id(session_id, root)
    if resolved is None:
        err_console.print(f"[red]No session matches {session_id!r}.[/red]")
        raise SystemExit(1)

    events = load_session(resolved, root=root)
    if not events:
        err_console.print(f"[yellow]Session {resolved} has no events.[/yellow]")
        raise SystemExit(1)

    console.rule(f"[bold]{resolved}[/bold]  ({len(events)} events)")

    for ev in events:
        if type_filter and ev.type != type_filter:
            continue
        console.print(_event_line(ev, None))
        if full:
            payload = json.dumps(ev.payload, indent=2, default=str)
            console.print(
                Panel(
                    Syntax(payload, "json", theme="monokai", word_wrap=True),
                    title=f"seq {ev.seq} payload",
                    border_style="dim",
                )
            )


@main.command("play")
@click.argument("session_id", required=False)
@click.option("--root", default=None)
@click.option("--speed", default=1.0, type=float, help="Playback speed (2.0 = faster).")
@click.option("--step", is_flag=True, help="Advance one event at a time.")
@click.option("--no-animate", is_flag=True, help="Print all events at once.")
@click.option("-s", "--speak", is_flag=True, help="Speak each event aloud via OS TTS.")
@click.option("--rate", default=175, type=int, show_default=True, help="TTS speed in words/min.")
@click.option("--voice", default=None, help="TTS voice name (see: bikem voices).")
def cmd_play(
    session_id: str | None,
    root: str | None,
    speed: float,
    step: bool,
    no_animate: bool,
    speak: bool,
    rate: int,
    voice: str | None,
) -> None:
    """Play back a session trace like a video. Defaults to the latest session."""
    session_id = session_id or "last"
    resolved = _resolve_id(session_id, root)
    if resolved is None:
        err_console.print(f"[red]No session matches {session_id!r}.[/red]")
        raise SystemExit(1)

    events = load_session(resolved, root=root)
    if not events:
        err_console.print(f"[yellow]Session {resolved} has no events.[/yellow]")
        raise SystemExit(1)

    start = next((e for e in events if e.type == EventType.SESSION_START.value), events[0])
    end = next((e for e in reversed(events) if e.type == EventType.SESSION_END.value), events[-1])
    name = (start.payload or {}).get("name") or "unnamed"
    base = _parse_ts(start.ts)
    end_ts = _parse_ts(end.ts)
    duration = (end_ts - base).total_seconds() if base and end_ts else 0.0

    drifts = sum(1 for e in events if e.type == EventType.DRIFT_FLAG.value)
    errors = sum(1 for e in events if e.type == EventType.ERROR.value)

    speaker = Speaker(rate=rate, enabled=speak, voice=voice) if speak else None

    header = Text()
    header.append("  bikem", style="bold")
    header.append("  \u00b7  ", style="dim")
    header.append(resolved, style="cyan")
    header.append("  \u00b7  ", style="dim")
    header.append(f'"{name}"', style="bold")
    header.append("        ")
    header.append(f"{len(events)} events", style="")
    header.append("  \u00b7  ", style="dim")
    header.append(f"{duration:.2f}s", style="")
    header.append("  \u00b7  ", style="dim")
    if drifts or errors:
        header.append(f"{drifts} drift \u00b7 {errors} errors", style="bold red")
    else:
        header.append("clean", style="green")
    if speaker and speaker.available:
        header.append("  \u00b7  ", style="dim")
        header.append(f"voice: {speaker.backend}", style="dim")
    console.print(header)
    console.rule(style="dim")

    lines = [_event_line(ev, base) for ev in events]

    # ---- Phase 1: visual ----
    if no_animate or step:
        for ln in lines:
            console.print(ln)
            if step:
                try:
                    console.input("[dim]  \u21b5 [/dim]")
                except (EOFError, KeyboardInterrupt):
                    break
    else:
        delay = 0.4 / max(speed, 0.1)
        try:
            for ln in lines:
                console.print(ln)
                time.sleep(delay)
        except KeyboardInterrupt:
            pass

    console.print()

    # ---- Phase 2: audio (independent of phase 1) ----
    if speaker and speaker.available:
        summary = narrate(events)
        console.print("  [dim]\u2500 narration \u2500[/dim]")
        console.print(f"  [italic]{summary}[/italic]")
        console.print()
        try:
            speaker.say(summary)
        except KeyboardInterrupt:
            pass
        console.print("  [dim]narrated[/dim]")
        console.print()


@main.command("diff")
@click.argument("left_id", required=False)
@click.argument("right_id", required=False)
@click.option("--root", default=None)
@click.option("--full", is_flag=True, help="Show full payloads for each divergence.")
def cmd_diff(left_id: str | None, right_id: str | None, root: str | None, full: bool) -> None:
    """Compare two sessions and report where they first diverge.

    With no arguments, compares the two most recent sessions.
    """
    left_id = left_id or "last~1"
    right_id = right_id or "last"
    left = _resolve_id(left_id, root)
    right = _resolve_id(right_id, root)
    if left is None:
        err_console.print(f"[red]No session matches {left_id!r}.[/red]")
        raise SystemExit(1)
    if right is None:
        err_console.print(f"[red]No session matches {right_id!r}.[/red]")
        raise SystemExit(1)

    result = diff_sessions(left, right, root=root)

    header = Text()
    header.append("  diff  ", style="bold")
    header.append("  \u00b7  ", style="dim")
    header.append(left, style="cyan")
    header.append("  \u2194  ", style="dim")
    header.append(right, style="cyan")
    console.print(header)
    console.print(f"  [dim]left:  {result.left_count} events[/dim]")
    console.print(f"  [dim]right: {result.right_count} events[/dim]")
    console.rule(style="dim")

    if result.identical:
        console.print(f"  [green]\u2713 identical[/green]  {result.left_count} events match")
        return

    summary = diff_summarize(result)
    console.print(f"  [bold red]\u2717 {summary}[/bold red]")
    console.print()

    for d in result.divergences[:20]:
        seq_txt = f"#{d.seq:<4}"
        kind_style = {
            "type_mismatch": "bold red",
            "content_mismatch": "yellow",
            "missing": "magenta",
            "extra": "magenta",
        }.get(d.kind, "white")
        console.print(f"  {seq_txt} [{kind_style}]{d.kind}[/{kind_style}]  {d.detail}")
        if full:
            if d.left is not None:
                console.print(
                    Panel(
                        Syntax(
                            json.dumps(d.left.payload, indent=2, default=str),
                            "json",
                            theme="monokai",
                            word_wrap=True,
                        ),
                        title=f"left seq {d.left.seq}",
                        border_style="cyan",
                    )
                )
            if d.right is not None:
                console.print(
                    Panel(
                        Syntax(
                            json.dumps(d.right.payload, indent=2, default=str),
                            "json",
                            theme="monokai",
                            word_wrap=True,
                        ),
                        title=f"right seq {d.right.seq}",
                        border_style="yellow",
                    )
                )

    if len(result.divergences) > 20:
        console.print(f"  [dim]... {len(result.divergences) - 20} more[/dim]")

    raise SystemExit(2)


@main.command("verify")
@click.argument("session_id", required=False)
@click.option("--root", default=None)
def cmd_verify(session_id: str | None, root: str | None) -> None:
    """Verify the hash chain of a session. Defaults to the latest session."""
    session_id = session_id or "last"
    resolved = _resolve_id(session_id, root)
    if resolved is None:
        err_console.print(f"[red]No session matches {session_id!r}.[/red]")
        raise SystemExit(1)

    events = load_session(resolved, root=root)
    ok, bad = verify_chain(events)
    if ok:
        console.print(f"[green]OK[/green] {resolved}: {len(events)} events, chain intact")
        return
    console.print(f"[red]BROKEN[/red] {resolved}: first bad event at seq {bad}")
    raise SystemExit(2)


@main.command("path")
@click.argument("session_id", required=False)
@click.option("--root", default=None)
def cmd_path(session_id: str | None, root: str | None) -> None:
    """Print the raw JSONL path for a session. Defaults to the latest session."""
    session_id = session_id or "last"
    resolved = _resolve_id(session_id, root)
    if resolved is None:
        err_console.print(f"[red]No session matches {session_id!r}.[/red]")
        raise SystemExit(1)
    store = SessionStore(session_id=resolved, root=root)
    click.echo(str(store.path))


@main.command("stats")
@click.option("--root", default=None)
def cmd_stats(root: str | None) -> None:
    """Summary across all sessions."""
    sessions = list_sessions(root=root)
    if not sessions:
        console.print("[dim]No sessions yet.[/dim]")
        return

    total_events = 0
    total_bytes = 0
    by_type: dict[str, int] = {}
    for s in sessions:
        total_bytes += s["size"]
        for ev in SessionStore(session_id=s["session_id"], root=root).iter_events():
            total_events += 1
            by_type[ev.type] = by_type.get(ev.type, 0) + 1

    console.print(
        Panel.fit(
            f"[bold]{len(sessions)}[/bold] sessions   "
            f"[bold]{total_events}[/bold] events   "
            f"[bold]{_human_size(total_bytes)}[/bold] on disk",
            border_style="cyan",
        )
    )

    if by_type:
        t = Table(show_header=True, header_style="bold")
        t.add_column("Event type")
        t.add_column("Count", justify="right")
        for k in sorted(by_type, key=lambda k: -by_type[k]):
            style = _TYPE_STYLE.get(k, "white")
            t.add_row(f"[{style}]{k}[/{style}]", str(by_type[k]))
        console.print(t)


@main.command("speak")
@click.argument("session_id", required=False)
@click.option("--root", default=None)
@click.option("--rate", default=175, type=int, show_default=True, help="TTS speed in words/min.")
@click.option("--voice", default=None, help="TTS voice name (see: bikem voices).")
def cmd_speak(session_id: str | None, root: str | None, rate: int, voice: str | None) -> None:
    """Narrate a session aloud. No visual output. Defaults to the latest session."""
    session_id = session_id or "last"
    resolved = _resolve_id(session_id, root)
    if resolved is None:
        err_console.print(f"[red]No session matches {session_id!r}.[/red]")
        raise SystemExit(1)

    events = load_session(resolved, root=root)
    if not events:
        err_console.print(f"[yellow]Session {resolved} has no events.[/yellow]")
        raise SystemExit(1)

    speaker = Speaker(rate=rate, enabled=True, voice=voice)
    if not speaker.available:
        err_console.print("[red]No TTS backend available.[/red]")
        err_console.print("[dim]Ubuntu: sudo apt install espeak-ng[/dim]")
        raise SystemExit(1)

    summary = narrate(events)
    console.print(f"  [dim]speaking {resolved} ({len(events)} events via {speaker.backend})[/dim]")
    console.print(f"  [italic]{summary}[/italic]")
    console.print()
    try:
        speaker.say(summary)
    except KeyboardInterrupt:
        pass
    console.print("  [dim]done[/dim]")


@main.command("voices")
def cmd_voices() -> None:
    """List available TTS voices on this machine."""
    names = list_voices()
    if not names:
        console.print("[yellow]No TTS voices detected.[/yellow]")
        console.print("[dim]Ubuntu: sudo apt install espeak-ng[/dim]")
        raise SystemExit(1)

    console.print(f"  [bold]{len(names)} voice(s) available[/bold]")
    console.print()
    for n in names:
        console.print(f"  [cyan]{n}[/cyan]")
    console.print()
    console.print('  [dim]Use with: bikem play <id> --speak --voice "<name>"[/dim]')


@main.command("last")
@click.option("-n", "--count", default=1, show_default=True, help="Print N most recent ids.")
@click.option("--root", default=None)
def cmd_last(count: int, root: str | None) -> None:
    """Print the most recent session id. Pipeable."""
    sessions = list_sessions(root=root)
    if not sessions:
        err_console.print("[yellow]No sessions recorded yet.[/yellow]")
        raise SystemExit(1)
    for s in sessions[: max(1, count)]:
        click.echo(s["session_id"])


if __name__ == "__main__":
    main()
