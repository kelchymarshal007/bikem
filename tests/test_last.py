import os
from pathlib import Path

import httpx
from click.testing import CliRunner

from bikem import session
from bikem.cli.main import main


def _make(root: Path, name: str) -> str:
    os.environ["BIKEM_HOME"] = str(root)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with session(name) as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.post(
                "https://api.openai.com/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )
    return s.session_id


def test_last_prints_newest(tmp_path: Path):
    _make(tmp_path, "one")
    sid2 = _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["last", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid2 in r.output


def test_last_count(tmp_path: Path):
    sid1 = _make(tmp_path, "one")
    sid2 = _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["last", "-n", "2", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid1 in r.output
    assert sid2 in r.output


def test_last_empty(tmp_path: Path):
    r = CliRunner().invoke(main, ["last", "--root", str(tmp_path)])
    assert r.exit_code == 1


def test_play_last_keyword(tmp_path: Path):
    _make(tmp_path, "one")
    sid2 = _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["play", "last", "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 0
    assert sid2 in r.output


def test_play_last_tilde(tmp_path: Path):
    sid1 = _make(tmp_path, "one")
    _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["play", "last~1", "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 0
    assert sid1 in r.output


def test_play_last_tilde_out_of_range(tmp_path: Path):
    _make(tmp_path, "one")
    r = CliRunner().invoke(main, ["play", "last~5", "--root", str(tmp_path), "--no-animate"])
    assert r.exit_code == 1


def test_show_no_arg_uses_last(tmp_path: Path):
    _make(tmp_path, "one")
    sid2 = _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["show", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid2 in r.output


def test_show_latest_alias(tmp_path: Path):
    _make(tmp_path, "one")
    sid2 = _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["show", "latest", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid2 in r.output


def test_show_prev(tmp_path: Path):
    sid1 = _make(tmp_path, "one")
    _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["show", "prev", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert sid1 in r.output


def test_diff_no_args_compares_two_newest(tmp_path: Path):
    _make(tmp_path, "one")
    _make(tmp_path, "two")
    r = CliRunner().invoke(main, ["diff", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "identical" in r.output
