import bikem
from bikem import session
from bikem.events import EventType
from bikem.store import load_session


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEM_HOME", str(tmp_path))


def test_tool_records_call_and_result(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    @bikem.tool("add")
    def add(a, b):
        return a + b

    with session("tools") as s:
        assert add(2, 3) == 5

    events = load_session(s.session_id, root=tmp_path)
    types = [e.type for e in events]
    assert EventType.TOOL_CALL.value in types
    assert EventType.TOOL_RESULT.value in types
    call = next(e for e in events if e.type == EventType.TOOL_CALL.value)
    assert call.payload["name"] == "add"


def test_tool_noop_outside_session(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    @bikem.tool()
    def double(x):
        return x * 2

    assert double(5) == 10


def test_tool_records_error(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    @bikem.tool()
    def blow_up():
        raise ValueError("nope")

    with session("tools") as s:
        try:
            blow_up()
        except ValueError:
            pass

    events = load_session(s.session_id, root=tmp_path)
    types = [e.type for e in events]
    assert EventType.TOOL_CALL.value in types
    assert EventType.ERROR.value in types


def test_tool_default_name(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    @bikem.tool()
    def my_custom_tool():
        return "ok"

    with session("tools") as s:
        my_custom_tool()

    events = load_session(s.session_id, root=tmp_path)
    call = next(e for e in events if e.type == EventType.TOOL_CALL.value)
    assert call.payload["name"] == "my_custom_tool"


def test_tool_non_serializable(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    class Weird:
        def __repr__(self):
            return "<Weird>"

    @bikem.tool()
    def make_weird():
        return Weird()

    with session("tools") as s:
        result = make_weird()
        assert isinstance(result, Weird)

    events = load_session(s.session_id, root=tmp_path)
    result_ev = next(e for e in events if e.type == EventType.TOOL_RESULT.value)
    assert result_ev.payload["result"] == "<Weird>"
