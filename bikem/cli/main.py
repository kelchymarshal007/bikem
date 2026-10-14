"""bikem command-line interface.

Commands:

    bikem list              List recent sessions
    bikem show <id>         Pretty-print a session trace
    bikem verify <id>       Verify hash chain integrity
    bikem path <id>         Print the raw JSONL file path
    bikem stats             Summary across all sessions
"""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..events import Event, EventType, verify_chain
from ..store import SessionStore, list_sessions, load_session

console = Console()
err_console = Console(stderr=True)

# Colours per event type -- keeps a long trace scannable at a glance.
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


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f}TB"


def _shorten(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "..."


def _summary_line(ev: Event) -> Text:
    style = _TYPE_STYLE.get(ev.type, "white")
    t = Text()
    t.append(f"{ev.seq:>4}  ", style="dim")
    t.append(ev.ts or "", style="dim")
    t.append("  ")
    t.append(f"{ev.type:<16}", style=style)

    p = ev.payload or {}
    if ev.type == EventType.LLM_REQUEST.value:
        model = p.get("model") or "?"
        t.append(f" {model}  ", style="bold")
        body = p.get("body") or {}
        if isinstance(body, dict):
            msgs = body.get("messages")
            if isinstance(msgs, list):
                t.append(f"{len(msgs)} msgs")
    elif ev.type == EventType.LLM_RESPONSE.value:
        t.append(f" status={p.get('status')}")
        if p.get("streaming"):
            t.append("  streaming", style="dim")
        body = p.get("body") or {}
        if isinstance(body, dict):
            choices = body.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {}).get("content", "")
                if isinstance(msg, str) and msg:
                    t.append("  " + _shorten(msg))
    elif ev.type == EventType.ERROR.value:
        t.append(f" {p.get('error', '')}", style="red")
    elif ev.type == EventType.SESSION_START.value:
        t.append(f" {p.get('name', '')}")
    else:
        body = json.dumps(p, default=str)
        if body != "{}":
            t.append(" " + _shorten(body))
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

    from datetime import datetime

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
    """Allow prefix matching: `bikem show 3f9a` finds sess_...3f9a..."""
    known = {s["session_id"] for s in list_sessions(root=root)}
    if session_id in known:
        return session_id
    matches = [sid for sid in known if sid.endswith(session_id) or session_id in sid]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        err_console.print(f"[red]Ambiguous:[/red] {', '.join(sorted(matches))}")
    return None


@main.command("show")
@click.argument("session_id")
@click.option("--root", default=None)
@click.option("--full", is_flag=True, help="Print full payload JSON for every event.")
@click.option("--type", "type_filter", default=None, help="Only show events of this type.")
def cmd_show(session_id: str, root: str | None, full: bool, type_filter: str | None) -> None:
    """Pretty-print a session trace."""
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
        console.print(_summary_line(ev))
        if full:
            payload = json.dumps(ev.payload, indent=2, default=str)
            console.print(
                Panel(
                    Syntax(payload, "json", theme="monokai", word_wrap=True),
                    title=f"seq {ev.seq} payload",
                    border_style="dim",
                )
            )


@main.command("verify")
@click.argument("session_id")
@click.option("--root", default=None)
def cmd_verify(session_id: str, root: str | None) -> None:
    """Verify the hash chain of a session."""
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
@click.argument("session_id")
@click.option("--root", default=None)
def cmd_path(session_id: str, root: str | None) -> None:
    """Print the raw JSONL path for a session."""
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


if __name__ == "__main__":
    main()
