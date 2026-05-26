# 方向键操作（删除 / 重命名）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TUI 里 → 右键重命名、← 左键删除真实会话文件（带确认），移除失效的 `r` 绑定；方向键用 `priority=True` 以便搜索框聚焦时也能触发。

**Architecture:** adapter 层新增删除能力（文件型 unlink，非文件型不支持）；SessionSearch 编排删除（删文件 + 清索引/覆盖/缓存）；新增 DeleteConfirmModal；app 绑定 left/right。

**Tech Stack:** Python 3、Textual、tantivy、pytest、uv。测试用 `uv run pytest <path> -v`；全量可靠结果用 `-n0`（已知 xdist flaky）。

---

## 文件结构

- 修改 `src/fast_resume/adapters/base.py` —— Protocol + BaseSessionAdapter 删除能力
- 修改 `src/fast_resume/adapters/crush.py`、`opencode.py`、`copilot_vscode.py` —— 声明不支持删除
- 修改 `src/fast_resume/search.py` —— can_delete / get_session_path / delete_session
- 修改 `src/fast_resume/tui/modal.py` + `styles.py` —— DeleteConfirmModal
- 修改 `src/fast_resume/tui/app.py` —— 绑定与 action
- 修改 `README.md`
- 测试：新增 `tests/test_delete.py`；扩展 `tests/test_search.py`、`tests/test_tui.py`

---

## Task 1: adapter 删除能力

**Files:**
- Modify: `src/fast_resume/adapters/base.py`
- Modify: `src/fast_resume/adapters/crush.py`, `opencode.py`, `copilot_vscode.py`
- Test: `tests/test_delete.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_delete.py`：

```python
"""Tests for session deletion capability across adapters."""

from fast_resume.adapters.claude import ClaudeAdapter
from fast_resume.adapters.crush import CrushAdapter
from fast_resume.adapters.opencode import OpenCodeAdapter
from fast_resume.adapters.copilot_vscode import CopilotVSCodeAdapter


def _make_claude_session_file(root, project="proj", sid="sess-abc"):
    proj = root / project
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / f"{sid}.jsonl"
    # one user message line so it's a valid-ish session file
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


def test_nonfile_adapters_do_not_support_delete():
    for adapter in (CrushAdapter(), OpenCodeAdapter(), CopilotVSCodeAdapter()):
        assert adapter.supports_delete is False
        assert adapter.delete_session("anything") is False
        assert adapter.get_session_path("anything") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_delete.py -v`
Expected: FAIL（`AttributeError: 'ClaudeAdapter' object has no attribute 'get_session_path'` 等）

- [ ] **Step 3: base.py 加协议与基类实现**

在 `AgentAdapter` Protocol 中（与 `supports_yolo` 同区）新增声明：

```python
    @property
    def supports_delete(self) -> bool:
        """Whether this adapter can delete a session's underlying file."""
        ...

    def delete_session(self, session_id: str) -> bool:
        """Delete the session's underlying file. Returns True on success."""
        ...

    def get_session_path(self, session_id: str) -> str | None:
        """Return the path of the session's file, or None if not found/unsupported."""
        ...
```

在 `BaseSessionAdapter` 中（`supports_yolo` 属性附近）新增：

```python
    @property
    def supports_delete(self) -> bool:
        """File-based adapters can delete the session's file."""
        return True

    def get_session_path(self, session_id: str) -> str | None:
        """Locate the session file for session_id via the file scan."""
        files = self._scan_session_files()
        entry = files.get(session_id)
        return str(entry[0]) if entry else None

    def delete_session(self, session_id: str) -> bool:
        """Delete the session's underlying file. Returns True on success."""
        files = self._scan_session_files()
        entry = files.get(session_id)
        if entry is None:
            return False
        try:
            entry[0].unlink()
            return True
        except OSError as e:
            logger.warning("Could not delete session file %s: %s", entry[0], e)
            return False
```

确认 `logger` 已在 base.py 顶部定义（`logger = logging.getLogger(__name__)`，已存在）。

- [ ] **Step 4: 三个非文件 adapter 声明不支持**

在 `crush.py`、`opencode.py`、`copilot_vscode.py` 各自的 Adapter 类体里加（放在类属性/方法区，紧跟现有 `name`/`color`/`badge` 或 `supports_yolo` 之后）：

```python
    supports_delete = False

    def delete_session(self, session_id: str) -> bool:
        return False

    def get_session_path(self, session_id: str) -> str | None:
        return None
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_delete.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 全量串行确认未破坏**

Run: `uv run pytest tests/ -n0 -q`
Expected: all pass

- [ ] **Step 7: 提交**

```bash
git add src/fast_resume/adapters/ tests/test_delete.py
git commit -m "feat(adapters): add session file deletion capability"
```

---

## Task 2: SessionSearch 删除编排

**Files:**
- Modify: `src/fast_resume/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_search.py` 末尾追加：

```python
def test_can_delete_reflects_adapter(temp_dir):
    from datetime import datetime
    from unittest.mock import MagicMock
    from fast_resume.adapters.base import Session
    from fast_resume.search import SessionSearch

    engine = SessionSearch()
    sess = Session(id="s1", agent="claude", title="t", directory="/tmp",
                   timestamp=datetime(2024, 1, 1), content="c", message_count=1)
    adapter = MagicMock()
    adapter.supports_delete = True
    engine.get_adapter_for_session = lambda s: adapter
    assert engine.can_delete(sess) is True
    adapter.supports_delete = False
    assert engine.can_delete(sess) is False


def test_delete_session_purges_everywhere(temp_dir):
    from datetime import datetime
    from unittest.mock import MagicMock
    from fast_resume.adapters.base import Session
    from fast_resume.index import TantivyIndex
    from fast_resume.overrides import TitleOverrides
    from fast_resume.search import SessionSearch

    engine = SessionSearch()
    engine._index = TantivyIndex(
        index_path=temp_dir / "idx",
        overrides=TitleOverrides(path=temp_dir / "ov.json"),
    )
    sess = Session(id="s1", agent="claude", title="t", directory="/tmp",
                   timestamp=datetime(2024, 1, 1), content="c", message_count=1)
    engine._index.add_sessions([sess])
    engine._index.overrides.set("s1", "custom")
    engine._sessions = [sess]
    engine._sessions_by_id = {"s1": sess}

    adapter = MagicMock()
    adapter.supports_delete = True
    adapter.delete_session.return_value = True
    engine.get_adapter_for_session = lambda s: adapter

    assert engine.delete_session(sess) is True
    adapter.delete_session.assert_called_once_with("s1")
    assert engine._index.get_all_sessions() == []
    assert engine._index.overrides.get("s1") is None
    assert "s1" not in engine._sessions_by_id
    assert engine._sessions == []


def test_delete_session_unsupported_returns_false(temp_dir):
    from datetime import datetime
    from unittest.mock import MagicMock
    from fast_resume.adapters.base import Session
    from fast_resume.search import SessionSearch

    engine = SessionSearch()
    sess = Session(id="s1", agent="crush", title="t", directory="/tmp",
                   timestamp=datetime(2024, 1, 1), content="c", message_count=1)
    adapter = MagicMock()
    adapter.supports_delete = False
    engine.get_adapter_for_session = lambda s: adapter
    assert engine.delete_session(sess) is False
    adapter.delete_session.assert_not_called()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_search.py -k "delete or can_delete" -v`
Expected: FAIL（`AttributeError: 'SessionSearch' object has no attribute 'can_delete'`）

- [ ] **Step 3: 实现**

在 `search.py` 的 `SessionSearch` 类中（`rename_session` 附近）新增：

```python
    def can_delete(self, session: Session) -> bool:
        adapter = self.get_adapter_for_session(session)
        return bool(adapter and adapter.supports_delete)

    def get_session_path(self, session: Session) -> str | None:
        adapter = self.get_adapter_for_session(session)
        if adapter is None or not adapter.supports_delete:
            return None
        return adapter.get_session_path(session.id)

    def delete_session(self, session: Session) -> bool:
        """Delete the session's real file, then purge it from index/overrides/caches.

        Returns True on success, False if unsupported or the file delete failed.
        """
        adapter = self.get_adapter_for_session(session)
        if adapter is None or not adapter.supports_delete:
            return False
        if not adapter.delete_session(session.id):
            return False
        self._index.delete_sessions([session.id])
        self._index.overrides.clear(session.id)
        self._sessions_by_id.pop(session.id, None)
        if self._sessions is not None:
            self._sessions = [s for s in self._sessions if s.id != session.id]
        return True
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_search.py -k "delete or can_delete" -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add src/fast_resume/search.py tests/test_search.py
git commit -m "feat(search): add delete_session/can_delete orchestration"
```

---

## Task 3: DeleteConfirmModal

**Files:**
- Modify: `src/fast_resume/tui/modal.py`, `src/fast_resume/tui/styles.py`

- [ ] **Step 1: 加 CSS**

在 `styles.py` 末尾追加：

```python
DELETE_MODAL_CSS = """
DeleteConfirmModal {
    align: center middle;
}

DeleteConfirmModal > Vertical {
    width: 70%;
    height: auto;
    padding: 1 2;
    background: $surface;
    border: thick $error;
}

DeleteConfirmModal #delete-title {
    width: 100%;
    content-align: center middle;
    color: $error;
    text-style: bold;
    margin-bottom: 1;
}

DeleteConfirmModal .delete-detail {
    width: 100%;
}

DeleteConfirmModal #delete-path {
    width: 100%;
    color: $text-muted;
    margin-bottom: 1;
}

DeleteConfirmModal #delete-buttons {
    width: 100%;
    height: auto;
    align: center middle;
}

DeleteConfirmModal #delete-buttons Button {
    margin: 0 1;
}
"""
```

- [ ] **Step 2: 加 DeleteConfirmModal**

在 `modal.py`：把 styles import 改为同时引入 `DELETE_MODAL_CSS`，例如：

```python
from .styles import DELETE_MODAL_CSS, RENAME_MODAL_CSS, YOLO_MODAL_CSS
```

（确认当前 import 行的实际内容并据此合并，不要假设；`Button`、`Label`、`Vertical`、`Horizontal`、`on`、`Binding`、`ComposeResult`、`ModalScreen` 应已 import。）

在文件末尾追加：

```python
class DeleteConfirmModal(ModalScreen[bool]):
    """Confirm permanent deletion of a session's underlying file.

    Dismisses True (delete) on `y`/Enter or the Delete button; False (cancel)
    on `n`/Escape or the Cancel button.
    """

    BINDINGS = [
        Binding("y", "confirm", "Delete", show=False),
        Binding("enter", "confirm", "Delete", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = DELETE_MODAL_CSS

    def __init__(self, title: str, agent: str, path: str) -> None:
        super().__init__()
        self._title = title
        self._agent = agent
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Delete this session permanently?", id="delete-title")
            yield Label(f"[{self._agent}] {self._title}", classes="delete-detail")
            yield Label(
                f"This will delete the file: {self._path}"
                if self._path
                else "This will delete the session file.",
                id="delete-path",
            )
            with Horizontal(id="delete-buttons"):
                yield Button("Cancel", id="delete-cancel-btn")
                yield Button("Delete", id="delete-confirm-btn", variant="error")

    def on_mount(self) -> None:
        self.query_one("#delete-cancel-btn", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#delete-confirm-btn")
    def on_confirm_pressed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#delete-cancel-btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(False)
```

- [ ] **Step 3: 冒烟导入**

Run: `uv run python -c "from fast_resume.tui.modal import DeleteConfirmModal; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 提交**

```bash
git add src/fast_resume/tui/modal.py src/fast_resume/tui/styles.py
git commit -m "feat(tui): add DeleteConfirmModal dialog"
```

---

## Task 4: app 绑定与 action

**Files:**
- Modify: `src/fast_resume/tui/app.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_tui.py` 的 `TestRenameAction` 之后追加（顶部已 import `Session`/`FastResumeApp`/`MagicMock`/`datetime`；如需 `patch` 已 import）：

```python
class TestDeleteAction:
    """Tests for the delete session action."""

    def _make_app(self):
        app = FastResumeApp()
        session = Session(
            id="s1", agent="claude", title="Doomed",
            directory="/tmp", timestamp=datetime(2024, 1, 1),
            content="hi", message_count=2, base_title="Doomed",
        )
        app.selected_session = session
        app.search_engine = MagicMock()
        return app, session

    def test_apply_delete_success_refreshes_table(self):
        app, session = self._make_app()
        app.search_engine.delete_session.return_value = True
        table = MagicMock()
        table.displayed_sessions = [session]
        app.query_one = MagicMock(return_value=table)
        app.notify = MagicMock()
        app._apply_delete(session)
        app.search_engine.delete_session.assert_called_once_with(session)
        table.update_sessions.assert_called_once()
        # the deleted session must be excluded from the refreshed list
        passed = table.update_sessions.call_args[0][0]
        assert session not in passed

    def test_apply_delete_failure_notifies(self):
        app, session = self._make_app()
        app.search_engine.delete_session.return_value = False
        app.query_one = MagicMock()
        app.notify = MagicMock()
        app._apply_delete(session)
        app.notify.assert_called_once()
        app.query_one.return_value.update_sessions.assert_not_called()

    def test_action_delete_unsupported_shows_toast_no_modal(self):
        app, session = self._make_app()
        app.search_engine.can_delete.return_value = False
        app.notify = MagicMock()
        app.push_screen = MagicMock()
        app.action_delete_session()
        app.notify.assert_called_once()
        app.push_screen.assert_not_called()

    def test_action_delete_supported_pushes_modal(self):
        app, session = self._make_app()
        app.search_engine.can_delete.return_value = True
        app.search_engine.get_session_path.return_value = "/path/s1.jsonl"
        app.push_screen = MagicMock()
        app.action_delete_session()
        app.push_screen.assert_called_once()
        from fast_resume.tui.modal import DeleteConfirmModal
        assert isinstance(app.push_screen.call_args[0][0], DeleteConfirmModal)
```

并加一个回归测试确认 `r` 不再绑定（追加到合适处，例如 `TestDeleteAction` 内或一个独立函数）：

```python
def test_r_key_not_bound():
    from fast_resume.tui.app import FastResumeApp
    keys = [getattr(b, "key", None) for b in FastResumeApp.BINDINGS]
    assert "r" not in keys
    assert "right" in keys
    assert "left" in keys
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tui.py -k "Delete or r_key" -v`
Expected: FAIL（`AttributeError: ... _apply_delete` / `r` 仍在绑定）

- [ ] **Step 3: 实现**

在 `app.py`：

(a) 修改 modal import：

```python
from .modal import DeleteConfirmModal, RenameModal, YoloModeModal
```

(b) BINDINGS 中删除这一行：

```python
        Binding("r", "rename_session", "Rename", priority=True),
```

并在 `c`/copy_path 绑定之后加：

```python
        Binding("right", "rename_session", "Rename", priority=True),
        Binding("left", "delete_session", "Delete", priority=True),
```

(c) 在 `action_rename_session`/`_apply_rename` 附近新增：

```python
    def action_delete_session(self) -> None:
        """Open a confirmation modal to permanently delete the selected session."""
        if not self.selected_session:
            return
        session = self.selected_session
        if not self.search_engine.can_delete(session):
            self.notify(
                f"Delete not supported for {session.agent}",
                severity="warning",
                timeout=3,
            )
            return
        path = self.search_engine.get_session_path(session) or ""

        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                self._apply_delete(session)

        self.push_screen(
            DeleteConfirmModal(session.title, session.agent, path), on_result
        )

    def _apply_delete(self, session: Session) -> None:
        """Apply a confirmed delete: purge the session and refresh the table."""
        if not self.search_engine.delete_session(session):
            self.notify("Delete failed", severity="error", timeout=3)
            return
        table = self.query_one(ResultsTable)
        remaining = [s for s in table.displayed_sessions if s.id != session.id]
        self.selected_session = table.update_sessions(remaining, self._current_query)
        self.notify("Session deleted", timeout=2)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_tui.py -k "Delete or r_key or Rename" -v`
Expected: PASS（含删除用例、r 回归、既有 rename 用例）

- [ ] **Step 5: 全量串行**

Run: `uv run pytest tests/ -n0 -q`
Expected: all pass

- [ ] **Step 6: 提交**

```bash
git add src/fast_resume/tui/app.py tests/test_tui.py
git commit -m "feat(tui): arrow keys for rename (right) and delete (left); drop r"
```

---

## Task 5: README 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 keybindings**

在 `README.md` 的「Preview & Actions」表格里，把之前新增的 `r` 行替换为方向键说明，并保持表格格式：

```
| `→`       | Rename selected session title         |
| `←`       | Delete selected session (permanent, confirms first) |
```

（即删除 `| `r`       | Rename session title ... |` 这一行，换成上面两行。）

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: document arrow-key rename/delete, remove r"
```

---

## 收尾验证

- [ ] **全量串行**：`uv run pytest tests/ -n0 -q` → 全绿
- [ ] **手动冒烟**：`uv run fr` → 默认（搜索框聚焦）→ 选中一条 Claude 会话按 → 改名生效；按 ← 弹确认框显示文件路径，`y`/Enter 删除（文件真消失、列表移除），`Esc` 取消；对 Crush/OpenCode 会话按 ← 显示"不支持"提示；确认按 `r` 不再触发改名（只会打进搜索框）
