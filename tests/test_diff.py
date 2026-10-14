import os
from pathlib import Path

import httpx

from bikem import session
from bikem.diff import diff_sessions, summarize


def _record(tmp_path: Path, name: str, replies: list[dict]) -> str:
    os.environ["BIKEM_HOME"] = str(tmp_path)
    it = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(it))

    with session(name) as s:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for i in range(len(replies)):
                client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": f"msg {i}"}],
                    },
                )
    return s.session_id


def test_identical_sessions(tmp_path: Path):
    a = _record(tmp_path, "one", [{"choices": [{"message": {"content": "hi"}}]}])
    b = _record(tmp_path, "two", [{"choices": [{"message": {"content": "hi"}}]}])
    result = diff_sessions(a, b, root=tmp_path)
    assert result.identical
    assert result.left_count == result.right_count


def test_content_mismatch(tmp_path: Path):
    a = _record(tmp_path, "one", [{"choices": [{"message": {"content": "yes"}}]}])
    b = _record(tmp_path, "two", [{"choices": [{"message": {"content": "no"}}]}])
    result = diff_sessions(a, b, root=tmp_path)
    assert not result.identical
    kinds = {d.kind for d in result.divergences}
    assert "content_mismatch" in kinds


def test_length_mismatch(tmp_path: Path):
    a = _record(tmp_path, "one", [{"choices": [{"message": {"content": "a"}}]}])
    b = _record(
        tmp_path,
        "two",
        [
            {"choices": [{"message": {"content": "a"}}]},
            {"choices": [{"message": {"content": "b"}}]},
        ],
    )
    result = diff_sessions(a, b, root=tmp_path)
    assert not result.identical
    assert result.left_count != result.right_count


def test_summarize_identical(tmp_path: Path):
    a = _record(tmp_path, "one", [{"choices": [{"message": {"content": "x"}}]}])
    b = _record(tmp_path, "two", [{"choices": [{"message": {"content": "x"}}]}])
    result = diff_sessions(a, b, root=tmp_path)
    assert "identical" in summarize(result)
