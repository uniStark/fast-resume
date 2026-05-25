# fast-resume 自定义标题（title override）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 fast-resume TUI 里按 `r` 给会话改名，自定义标题持久化到独立覆盖层、可被搜索命中、`--rebuild` 后保留、清空可恢复原始标题。

**Architecture:** 新增独立 `TitleOverrides` 覆盖层（JSON，存于数据目录而非 cache）。在 Tantivy 文档构建的唯一咽喉点叠加覆盖：`title` 字段存「生效标题」（被索引、可搜索），新增 stored-only `base_title` 字段存解析出的原始标题（用于清空恢复）。TUI 加 `r` 键弹框改名。

**Tech Stack:** Python 3、Textual（TUI）、tantivy（全文索引）、orjson、pytest、uv。

测试命令统一用：`uv run pytest <路径> -v`

---

## 文件结构

- 新增 `src/fast_resume/overrides.py` —— `TitleOverrides` 覆盖层（JSON 读写）
- 新增 `tests/test_overrides.py` —— 覆盖层单测
- 修改 `src/fast_resume/config.py` —— 新增 `DATA_DIR`、`TITLE_OVERRIDES_FILE`
- 修改 `src/fast_resume/adapters/base.py` —— `Session` 加 `base_title` 字段
- 修改 `src/fast_resume/index.py` —— schema 加 `base_title`、`SCHEMA_VERSION` 20→21、抽 `_build_document` 并叠加覆盖、`_doc_to_session` 读 `base_title`、`__init__` 注入 overrides
- 修改 `src/fast_resume/search.py` —— 新增 `rename_session()`
- 修改 `src/fast_resume/tui/modal.py` —— 新增 `RenameModal`
- 修改 `src/fast_resume/tui/styles.py` —— 新增 `RENAME_MODAL_CSS`
- 修改 `src/fast_resume/tui/results_table.py` —— 新增 `refresh_displayed()`
- 修改 `src/fast_resume/tui/app.py` —— 加 `r` 绑定与 `action_rename_session()`
- 修改 `tests/test_index.py` —— 覆盖叠加 / 恢复 / 搜索命中 用例
- 修改 `README.md` —— Keybindings 补 `r`

---

## Task 1: config.py 新增数据目录与覆盖文件路径

**Files:**
- Modify: `src/fast_resume/config.py`

- [ ] **Step 1: 新增路径常量**

在 `config.py` 的「Storage location」区块（`CACHE_DIR`/`INDEX_DIR`/`LOG_FILE` 附近）后追加：

```python
# Persistent user data (NOT cache - survives cache clears and must not be lost)
DATA_DIR = Path.home() / ".local" / "share" / "fast-resume"
TITLE_OVERRIDES_FILE = DATA_DIR / "title_overrides.json"
```

- [ ] **Step 2: 提交**

```bash
git add src/fast_resume/config.py
git commit -m "feat(config): add data dir and title overrides file path"
```

---

## Task 2: TitleOverrides 覆盖层

**Files:**
- Create: `src/fast_resume/overrides.py`
- Test: `tests/test_overrides.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_overrides.py`：

```python
"""Tests for the title overrides store."""

from fast_resume.overrides import TitleOverrides


def test_set_and_get(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("sess-1", "My custom title")
    assert store.get("sess-1") == "My custom title"


def test_get_missing_returns_none(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    assert store.get("nope") is None


def test_clear_removes_entry(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("sess-1", "Custom")
    store.clear("sess-1")
    assert store.get("sess-1") is None


def test_clear_missing_is_noop(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.clear("nope")  # must not raise
    assert store.get("nope") is None


def test_persists_across_instances(temp_dir):
    path = temp_dir / "overrides.json"
    TitleOverrides(path=path).set("sess-1", "Persisted")
    assert TitleOverrides(path=path).get("sess-1") == "Persisted"


def test_all_returns_mapping(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("a", "A")
    store.set("b", "B")
    assert store.all() == {"a": "A", "b": "B"}


def test_corrupt_json_falls_back_to_empty(temp_dir):
    path = temp_dir / "overrides.json"
    path.write_text("{ this is not valid json")
    store = TitleOverrides(path=path)
    assert store.all() == {}
    # still usable after corruption
    store.set("sess-1", "Recovered")
    assert store.get("sess-1") == "Recovered"


def test_missing_file_is_empty(temp_dir):
    store = TitleOverrides(path=temp_dir / "does_not_exist.json")
    assert store.all() == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_overrides.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'fast_resume.overrides'`

- [ ] **Step 3: 实现 TitleOverrides**

创建 `src/fast_resume/overrides.py`：

```python
"""Persistent store for user-defined session title overrides.

Maps session_id -> custom title. Stored as JSON in the data directory
(NOT cache) so custom titles survive cache clears and index rebuilds.
"""

import logging
import os
from pathlib import Path

import orjson

from .config import TITLE_OVERRIDES_FILE

logger = logging.getLogger(__name__)


class TitleOverrides:
    """Read/write store of session title overrides backed by a JSON file."""

    def __init__(self, path: Path = TITLE_OVERRIDES_FILE) -> None:
        self._path = path
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = orjson.loads(self._path.read_bytes())
        except (orjson.JSONDecodeError, OSError) as e:
            logger.warning("Could not read title overrides at %s: %s", self._path, e)
            return {}
        if not isinstance(raw, dict):
            return {}
        # Keep only str -> str entries
        return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_bytes(orjson.dumps(self._data))
        os.replace(tmp, self._path)

    def get(self, session_id: str) -> str | None:
        return self._data.get(session_id)

    def set(self, session_id: str, title: str) -> None:
        self._data[session_id] = title
        self._save()

    def clear(self, session_id: str) -> None:
        if session_id in self._data:
            del self._data[session_id]
            self._save()

    def all(self) -> dict[str, str]:
        return dict(self._data)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_overrides.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add src/fast_resume/overrides.py tests/test_overrides.py
git commit -m "feat(overrides): add persistent title override store"
```

---

## Task 3: Session 加 base_title 字段

**Files:**
- Modify: `src/fast_resume/adapters/base.py`

- [ ] **Step 1: 加字段**

在 `Session` dataclass（`adapters/base.py`）的 `yolo: bool = False` 之后追加一行：

```python
    base_title: str = ""  # Parsed-from-source title before any override is applied
```

注意：放在所有现有字段之后、保持其它字段不动。因为有默认值，adapter 现有构造调用无需修改。

- [ ] **Step 2: 运行现有测试确认未破坏**

Run: `uv run pytest tests/ -v`
Expected: PASS（新增字段有默认值，不影响现有用例）

- [ ] **Step 3: 提交**

```bash
git add src/fast_resume/adapters/base.py
git commit -m "feat(session): add base_title field for original parsed title"
```

---

## Task 4: index.py 叠加覆盖、保留原始标题

**Files:**
- Modify: `src/fast_resume/index.py`
- Test: `tests/test_index.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_index.py` 顶部的 import 后加：

```python
from fast_resume.overrides import TitleOverrides
```

在 `tests/test_index.py` 的 `TestTantivyIndex` 类中追加以下用例（注意 fixture `index` 见下方 Step 2 的修改）：

```python
    def test_override_applied_to_title(self, temp_dir, sample_session):
        overrides = TitleOverrides(path=temp_dir / "ov.json")
        overrides.set(sample_session.id, "Renamed by user")
        idx = TantivyIndex(index_path=temp_dir / "idx", overrides=overrides)
        idx.add_sessions([sample_session])

        result = idx.get_all_sessions()[0]
        assert result.title == "Renamed by user"
        assert result.base_title == "Test session"

    def test_override_searchable(self, temp_dir, sample_session):
        overrides = TitleOverrides(path=temp_dir / "ov.json")
        overrides.set(sample_session.id, "Zebraphone")
        idx = TantivyIndex(index_path=temp_dir / "idx", overrides=overrides)
        idx.add_sessions([sample_session])

        hits = idx.search("Zebraphone")
        assert any(s.id == sample_session.id for s in hits)

    def test_clearing_override_restores_base_title(self, temp_dir, sample_session):
        overrides = TitleOverrides(path=temp_dir / "ov.json")
        overrides.set(sample_session.id, "Temp name")
        idx = TantivyIndex(index_path=temp_dir / "idx", overrides=overrides)
        idx.add_sessions([sample_session])
        # Reload as it would be in the app, then clear and reindex
        reloaded = idx.get_all_sessions()[0]
        overrides.clear(sample_session.id)
        idx.update_sessions([reloaded])

        result = idx.get_all_sessions()[0]
        assert result.title == "Test session"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_index.py -k override -v`
Expected: FAIL，`TypeError: __init__() got an unexpected keyword argument 'overrides'`

- [ ] **Step 3: `TantivyIndex.__init__` 注入 overrides**

在 `index.py` 顶部 import 区加：

```python
from .overrides import TitleOverrides
```

修改 `TantivyIndex.__init__`（当前签名 `def __init__(self, index_path: Path = INDEX_DIR) -> None:`）为：

```python
    def __init__(
        self,
        index_path: Path = INDEX_DIR,
        overrides: TitleOverrides | None = None,
    ) -> None:
        self.index_path = index_path
        self._index: tantivy.Index | None = None
        self._schema: tantivy.Schema | None = None
        self._version_file = index_path / _VERSION_FILE
        self.overrides = overrides if overrides is not None else TitleOverrides()
```

- [ ] **Step 4: schema 加 base_title 字段并 bump 版本**

在 `_build_schema` 中，`title` 字段那行之后加（base_title 仅存储、不索引）：

```python
        # Base title - the parsed-from-source title, stored only (not searched).
        # Used to restore the original title when an override is cleared.
        schema_builder.add_text_field("base_title", stored=True, indexed=False)
```

在 `config.py` 把 `SCHEMA_VERSION` 由 `20` 改为 `21`，并更新其行内注释：

```python
SCHEMA_VERSION = (
    21  # Bump when schema changes (21: add stored base_title for title overrides)
)
```

- [ ] **Step 5: 抽取 `_build_document` 并叠加覆盖**

在 `index.py` 的 `add_sessions` 之前新增私有方法：

```python
    def _build_document(self, session: Session) -> tantivy.Document:
        """Build a Tantivy document, applying any title override.

        `title` holds the effective (possibly overridden) title and is searchable.
        `base_title` holds the original parsed title for restoring on clear.
        """
        base = session.base_title or session.title
        effective = self.overrides.get(session.id) or base
        return tantivy.Document(
            id=session.id,
            title=effective,
            base_title=base,
            directory=session.directory,
            agent=session.agent,
            content=session.content,
            timestamp=session.timestamp.timestamp(),
            message_count=session.message_count,
            mtime=session.mtime,
            yolo=session.yolo,
        )
```

把 `add_sessions` 的循环体替换为：

```python
        index = self._ensure_index()
        writer = index.writer()
        for session in sessions:
            writer.add_document(self._build_document(session))
        writer.commit()
```

把 `update_sessions` 的循环体替换为：

```python
        index = self._ensure_index()
        writer = index.writer()
        # Delete existing documents first
        for session in sessions:
            writer.delete_documents_by_term("id", session.id)
        # Add new versions
        for session in sessions:
            writer.add_document(self._build_document(session))
        writer.commit()
```

- [ ] **Step 6: `_doc_to_session` 读出 base_title**

在 `_doc_to_session` 的 `Session(...)` 构造里加一行（放在 `yolo=...` 之后）：

```python
                base_title=doc.get_first("base_title") or "",
```

- [ ] **Step 7: 运行确认通过**

Run: `uv run pytest tests/test_index.py -v`
Expected: PASS（含 3 个新用例与全部既有用例）

- [ ] **Step 8: 提交**

```bash
git add src/fast_resume/index.py src/fast_resume/config.py tests/test_index.py
git commit -m "feat(index): apply title overrides, store base_title, bump schema to 21"
```

---

## Task 5: SessionSearch.rename_session

**Files:**
- Modify: `src/fast_resume/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_search.py` 末尾追加（若文件无 `Session`/`SessionSearch` import 则在顶部补上 `from fast_resume.adapters.base import Session` 和 `from fast_resume.search import SessionSearch`）：

```python
def test_rename_session_sets_override_and_title(temp_dir, monkeypatch):
    from datetime import datetime
    from fast_resume.adapters.base import Session
    from fast_resume.index import TantivyIndex
    from fast_resume.overrides import TitleOverrides
    from fast_resume.search import SessionSearch

    engine = SessionSearch()
    engine._index = TantivyIndex(
        index_path=temp_dir / "idx",
        overrides=TitleOverrides(path=temp_dir / "ov.json"),
    )
    session = Session(
        id="s1", agent="claude", title="Original",
        directory="/tmp", timestamp=datetime(2024, 1, 1),
        content="hello", message_count=2, base_title="Original",
    )
    engine._index.add_sessions([session])

    effective = engine.rename_session(session, "Brand New")

    assert effective == "Brand New"
    assert session.title == "Brand New"
    assert engine._index.overrides.get("s1") == "Brand New"
    assert engine._index.get_all_sessions()[0].title == "Brand New"


def test_rename_session_empty_restores_base(temp_dir):
    from datetime import datetime
    from fast_resume.adapters.base import Session
    from fast_resume.index import TantivyIndex
    from fast_resume.overrides import TitleOverrides
    from fast_resume.search import SessionSearch

    engine = SessionSearch()
    engine._index = TantivyIndex(
        index_path=temp_dir / "idx",
        overrides=TitleOverrides(path=temp_dir / "ov.json"),
    )
    session = Session(
        id="s1", agent="claude", title="Custom",
        directory="/tmp", timestamp=datetime(2024, 1, 1),
        content="hello", message_count=2, base_title="Original",
    )
    engine._index.overrides.set("s1", "Custom")
    engine._index.add_sessions([session])

    effective = engine.rename_session(session, "   ")  # blank -> restore

    assert effective == "Original"
    assert session.title == "Original"
    assert engine._index.overrides.get("s1") is None
    assert engine._index.get_all_sessions()[0].title == "Original"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_search.py -k rename -v`
Expected: FAIL，`AttributeError: 'SessionSearch' object has no attribute 'rename_session'`

- [ ] **Step 3: 实现 rename_session**

在 `search.py` 的 `SessionSearch` 类中（`search` 方法附近）新增：

```python
    def rename_session(self, session: Session, new_title: str) -> str:
        """Set or clear a custom title for a session.

        Blank input clears the override and restores the original parsed title.
        Mutates `session.title` to the effective title, persists the override,
        and reindexes the session. Returns the effective title.
        """
        cleaned = new_title.strip()
        base = session.base_title or session.title
        if cleaned:
            self._index.overrides.set(session.id, cleaned)
            session.title = cleaned
        else:
            self._index.overrides.clear(session.id)
            session.title = base
        self._index.update_sessions([session])
        return session.title
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_search.py -k rename -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/fast_resume/search.py tests/test_search.py
git commit -m "feat(search): add rename_session for title overrides"
```

---

## Task 6: RenameModal 弹窗

**Files:**
- Modify: `src/fast_resume/tui/modal.py`
- Modify: `src/fast_resume/tui/styles.py`

- [ ] **Step 1: 加 CSS**

在 `src/fast_resume/tui/styles.py` 末尾追加（与 `YOLO_MODAL_CSS` 同风格的居中弹框）：

```python
RENAME_MODAL_CSS = """
RenameModal {
    align: center middle;
}

RenameModal > Vertical {
    width: 60%;
    height: auto;
    padding: 1 2;
    background: $surface;
    border: thick $primary;
}

RenameModal #rename-title {
    width: 100%;
    content-align: center middle;
    margin-bottom: 1;
}

RenameModal #rename-input {
    width: 100%;
}

RenameModal #rename-hint {
    width: 100%;
    color: $text-muted;
    margin-top: 1;
}
"""
```

- [ ] **Step 2: 加 RenameModal**

在 `src/fast_resume/tui/modal.py` 中：把 `styles` import 改为同时引入新 CSS——

```python
from .styles import YOLO_MODAL_CSS, RENAME_MODAL_CSS
```

并把 widgets import 行改为包含 `Input`：

```python
from textual.widgets import Button, Input, Label
```

然后在文件末尾追加：

```python
class RenameModal(ModalScreen[str | None]):
    """Modal to rename a session's title.

    Dismisses with the new title string on Enter (empty string means
    "clear/restore"), or None on Escape (cancel, no change).
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = RENAME_MODAL_CSS

    def __init__(self, current_title: str = "") -> None:
        super().__init__()
        self._current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Rename session", id="rename-title")
            yield Input(value=self._current_title, id="rename-input")
            yield Label(
                "Enter to save · empty to restore original · Esc to cancel",
                id="rename-hint",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#rename-input")
    def on_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
```

- [ ] **Step 3: 冒烟测试导入**

Run: `uv run python -c "from fast_resume.tui.modal import RenameModal; print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 4: 提交**

```bash
git add src/fast_resume/tui/modal.py src/fast_resume/tui/styles.py
git commit -m "feat(tui): add RenameModal dialog"
```

---

## Task 7: ResultsTable 行内刷新

**Files:**
- Modify: `src/fast_resume/tui/results_table.py`

- [ ] **Step 1: 加 refresh_displayed 方法**

在 `ResultsTable`（`results_table.py`）的 `get_selected_session` 方法之前新增：

```python
    def refresh_displayed(self) -> None:
        """Re-render current rows in place, preserving cursor position.

        Call after mutating a displayed session (e.g. a title rename) so the
        table reflects the change without losing the user's selection.
        """
        row = self.cursor_row
        self._render_sessions()
        if row is not None and self._displayed_sessions:
            self.move_cursor(row=min(row, len(self._displayed_sessions) - 1))
```

- [ ] **Step 2: 冒烟测试导入**

Run: `uv run python -c "from fast_resume.tui.results_table import ResultsTable; print(hasattr(ResultsTable, 'refresh_displayed'))"`
Expected: 输出 `True`

- [ ] **Step 3: 提交**

```bash
git add src/fast_resume/tui/results_table.py
git commit -m "feat(tui): add ResultsTable.refresh_displayed for in-place updates"
```

---

## Task 8: app.py 绑定 r 键与 rename action

**Files:**
- Modify: `src/fast_resume/tui/app.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_tui.py` 末尾追加（顶部已 import `Session`、`FastResumeApp`、`MagicMock`）：

```python
class TestRenameAction:
    """Tests for the rename session action."""

    def _make_app_with_session(self):
        app = FastResumeApp()
        session = Session(
            id="s1", agent="claude", title="Original",
            directory="/tmp", timestamp=datetime(2024, 1, 1),
            content="hi", message_count=2, base_title="Original",
        )
        app.selected_session = session
        app.search_engine = MagicMock()
        return app, session

    def test_rename_callback_saves_new_title(self):
        app, session = self._make_app_with_session()
        app.search_engine.rename_session.return_value = "New Name"
        app.query_one = MagicMock()  # avoid DOM lookup (app not mounted)
        app.notify = MagicMock()
        # Simulate the modal returning a new title
        app._apply_rename(session, "New Name")
        app.search_engine.rename_session.assert_called_once_with(session, "New Name")
        app.query_one.return_value.refresh_displayed.assert_called_once()

    def test_rename_callback_ignores_cancel(self):
        app, session = self._make_app_with_session()
        app.query_one = MagicMock()
        app.notify = MagicMock()
        app._apply_rename(session, None)  # None == cancelled
        app.search_engine.rename_session.assert_not_called()
        app.query_one.return_value.refresh_displayed.assert_not_called()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_tui.py -k Rename -v`
Expected: FAIL，`AttributeError: 'FastResumeApp' object has no attribute '_apply_rename'`

- [ ] **Step 3: 加 import、绑定与 action**

在 `app.py` 顶部 modal import 处（当前引入 `YoloModeModal`）改为：

```python
from .modal import RenameModal, YoloModeModal
```

在 `BINDINGS` 列表中，`Binding("c", "copy_path", "Copy resume command", priority=True),` 之后加：

```python
        Binding("r", "rename_session", "Rename", priority=True),
```

在 `action_copy_path` 方法附近（UI actions 区之前的会话操作区）新增：

```python
    def action_rename_session(self) -> None:
        """Open a modal to rename the selected session's title."""
        if not self.selected_session:
            return
        session = self.selected_session

        def on_result(new_title: str | None) -> None:
            self._apply_rename(session, new_title)

        self.push_screen(RenameModal(session.title), on_result)

    def _apply_rename(self, session: Session, new_title: str | None) -> None:
        """Apply a rename result. None means the user cancelled (no change)."""
        if new_title is None:
            return
        effective = self.search_engine.rename_session(session, new_title)
        table = self.query_one(ResultsTable)
        table.refresh_displayed()
        self.notify(f"Renamed to: {effective}", timeout=2)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_tui.py -k Rename -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 跑全量测试**

Run: `uv run pytest tests/ -v`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
git add src/fast_resume/tui/app.py tests/test_tui.py
git commit -m "feat(tui): bind r to rename session title via RenameModal"
```

---

## Task 9: README 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 补 keybinding**

在 `README.md` 的 Keybindings 区块（含 `c` / Copy resume command 的表格或列表）加入一条，与既有条目同格式：

```
r — Rename session title (empty input restores the original)
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: document r key for renaming session titles"
```

---

## 收尾验证

- [ ] **全量测试**：`uv run pytest tests/ -v` → 全绿
- [ ] **手动冒烟**：`uv run fr` → 选中一条会话按 `r` → 改名保存 → 标题更新；用新标题搜索能命中；按 `r` 清空保存 → 恢复原标题；`fr --rebuild` 后自定义标题仍在
```
