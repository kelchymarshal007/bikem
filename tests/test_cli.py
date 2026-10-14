import os
from pathlib import Path

import httpx
from click.testing import CliRunner

from bikem import session
from bikem.cli.main import main


def _make_session(root: Path) -> str:
    os.environ["BIKEM_HOME"] = str(root)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with session("cli-demo") as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )
    return s.session_id


def test_list_shows_session(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["list", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid in r.output


def test_show_prints_events(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["show", sid, "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "llm.request" in r.output
    assert "llm.response" in r.output
    assert "gpt-4o" in r.output


def test_verify_ok(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["verify", sid, "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "OK" in r.output


def test_verify_prefix_match(tmp_path: Path):
    sid = _make_session(tmp_path)
    suffix = sid[-6:]
    r = CliRunner().invoke(main, ["verify", suffix, "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "OK" in r.output


def test_show_missing_session(tmp_path: Path):
    r = CliRunner().invoke(main, ["show", "nonexistent", "--root", str(tmp_path)])
    assert r.exit_code == 1


def test_stats(tmp_path: Path):
    _make_session(tmp_path)
    r = CliRunner().invoke(main, ["stats", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "sessions" in r.output
    assert "events" in r.output


def test_path(tmp_path: Path):
    sid = _make_session(tmp_path)
    r = CliRunner().invoke(main, ["path", sid, "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid in r.output
    assert ".jsonl" in r.output


def test_list_empty(tmp_path: Path):
    r = CliRunner().invoke(main, ["list", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "No sessions" in r.output
