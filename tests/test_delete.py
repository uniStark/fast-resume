"""Tests for session deletion capability across adapters."""

from fast_resume.adapters.claude import ClaudeAdapter
from fast_resume.adapters.crush import CrushAdapter
from fast_resume.adapters.opencode import OpenCodeAdapter
from fast_resume.adapters.copilot_vscode import CopilotVSCodeAdapter


def _make_claude_session_file(root, project="proj", sid="sess-abc"):
    proj = root / project
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / f"{sid}.jsonl"
    f.write_text(
        '{"type":"user","cwd":"/tmp","message":{"content":"hello there friend"}}\n'
        '{"type":"assistant","message":{"content":"hi"}}\n'
    )
    return f


def test_claude_get_session_path(temp_dir):
    f = _make_claude_session_file(temp_dir)
    adapter = ClaudeAdapter(sessions_dir=temp_dir)
    assert adapter.get_session_path("sess-abc") == str(f)


def test_claude_delete_session_removes_file(temp_dir):
    f = _make_claude_session_file(temp_dir)
    adapter = ClaudeAdapter(sessions_dir=temp_dir)
    assert adapter.supports_delete is True
    assert adapter.delete_session("sess-abc") is True
    assert not f.exists()


def test_claude_delete_missing_returns_false(temp_dir):
    _make_claude_session_file(temp_dir)
    adapter = ClaudeAdapter(sessions_dir=temp_dir)
    assert adapter.delete_session("does-not-exist") is False


def test_claude_delete_oserror_returns_false(temp_dir, monkeypatch):
    f = _make_claude_session_file(temp_dir)
    adapter = ClaudeAdapter(sessions_dir=temp_dir)

    def boom(self):
        raise OSError("permission denied")

    monkeypatch.setattr("pathlib.Path.unlink", boom)
    # Delete must not raise and must report failure; the file survives.
    assert adapter.delete_session("sess-abc") is False
    assert f.exists()


def test_nonfile_adapters_do_not_support_delete():
    for adapter in (CrushAdapter(), OpenCodeAdapter(), CopilotVSCodeAdapter()):
        assert adapter.supports_delete is False
        assert adapter.delete_session("anything") is False
        assert adapter.get_session_path("anything") is None
