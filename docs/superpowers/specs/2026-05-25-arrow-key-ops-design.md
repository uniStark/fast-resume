# fast-resume 方向键操作（删除 / 重命名）设计

- 日期：2026-05-25
- 状态：已通过澄清与设计确认，待 writing-plans
- 目标仓库：`uniStark/fast-resume`

## 背景

刚合并的"按 `r` 重命名"功能在实际使用中无效。根因经 systematic-debugging 定位：

- Textual 中 `priority=True` 的 App 绑定，对**单个可打印字符键**（`r`、以及既有的 `c`/`j`/`k`/`q`）在 `Input`（搜索框）聚焦时**不会拦截**——Input 把它当文本吃掉。app 启动默认聚焦搜索框，所以按 `r` 只是往搜索框打了个 "r"。
- 实测：焦点切到结果表格后按 `r` 能正常弹框（action 接线无误）；**非打印键**（方向键、F2、Ctrl+R 等）加 `priority=True` 时在搜索框聚焦下也能触发，且不污染搜索框、不移动搜索框光标（被 priority 绑定截走）。

用户选定的新交互：**选中会话后用方向键操作——← 左键删除（需确认），→ 右键重命名**。

## 决策（已与用户确认）

1. **改名触发由 `r` 改为 → 右键**，并**移除 `r` 绑定**。
2. **← 左键删除**：删除**真实会话文件**（彻底、不可逆），删除前弹确认框。
3. 确认框：`y` 与 `Enter` 都确认，`n` 与 `Esc` 取消。
4. 删除支持范围：仅"一会话一文件"的 agent（Claude、Codex、Copilot CLI、Vibe）；非文件存储的 agent（Copilot VSCode、Crush、OpenCode）不支持，提示后不动作。
5. 已接受的代价：搜索框内 left/right 不再移动光标（仍可退格/重打）。

## 详细设计

### 1. adapter 层 —— 删除能力

`src/fast_resume/adapters/base.py`：

- `AgentAdapter` Protocol 新增：
  - `supports_delete: bool`
  - `delete_session(self, session_id: str) -> bool`
  - `get_session_path(self, session_id: str) -> str | None`
- `BaseSessionAdapter`（文件型基类，被 Claude/Codex/Copilot/Vibe 继承）：
  - `supports_delete` 属性返回 `True`（与 `supports_yolo` 同形）。
  - `get_session_path(session_id)`：用 `_scan_session_files()` 取 `{id: (path, mtime)}`，返回匹配 id 的 `str(path)`，无则 `None`。
  - `delete_session(session_id)`：定位 path，存在则 `path.unlink()` 返回 `True`；找不到或 `OSError` 返回 `False`（记录日志）。

`src/fast_resume/adapters/{crush,opencode,copilot_vscode}.py`（非文件型）：
- 各加 `supports_delete = False`，以及满足协议的 `delete_session(self, _: str) -> bool: return False` 和 `get_session_path(self, _: str) -> str | None: return None`。

### 2. SessionSearch 层

`src/fast_resume/search.py`：

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

### 3. modal 层 —— DeleteConfirmModal

`src/fast_resume/tui/modal.py` 新增 `DeleteConfirmModal(ModalScreen[bool])`，`styles.py` 新增 `DELETE_MODAL_CSS`（镜像 YoloModeModal）：

- `__init__(self, title: str, agent: str, path: str)`。
- compose：警告标题（强调不可逆）、会话标题、agent、**将删除的文件路径**、Cancel/Delete 两个按钮。
- BINDINGS：`y`→confirm、`enter`→confirm、`n`→cancel、`escape`→cancel（均 `show=False`）。
- `action_confirm` → `dismiss(True)`；`action_cancel` → `dismiss(False)`。
- 按钮 `Delete`→dismiss(True)、`Cancel`→dismiss(False)（鼠标用）。

### 4. app 层

`src/fast_resume/tui/app.py`：

- BINDINGS：**删除** `Binding("r", "rename_session", ...)`；新增
  ```python
  Binding("right", "rename_session", "Rename", priority=True),
  Binding("left", "delete_session", "Delete", priority=True),
  ```
- `action_rename_session` 保持不变（现在由右键触发）。
- 新增：
  ```python
  def action_delete_session(self) -> None:
      if not self.selected_session:
          return
      session = self.selected_session
      if not self.search_engine.can_delete(session):
          self.notify(f"Delete not supported for {session.agent}",
                      severity="warning", timeout=3)
          return
      path = self.search_engine.get_session_path(session) or ""

      def on_result(confirmed: bool | None) -> None:
          if confirmed:
              self._apply_delete(session)

      self.push_screen(
          DeleteConfirmModal(session.title, session.agent, path), on_result
      )

  def _apply_delete(self, session: Session) -> None:
      if not self.search_engine.delete_session(session):
          self.notify("Delete failed", severity="error", timeout=3)
          return
      table = self.query_one(ResultsTable)
      remaining = [s for s in table.displayed_sessions if s.id != session.id]
      self.selected_session = table.update_sessions(remaining, self._current_query)
      self.notify("Session deleted", timeout=2)
  ```

### 5. 测试

- adapter：文件型删除（建临时文件→删除→文件消失、返回 True；找不到 id 返回 False）、`get_session_path` 正确；非文件型 `supports_delete is False`、`delete_session` 返回 False。
- SessionSearch：`delete_session` 成功路径（mock adapter 返回 True → 校验 `index.delete_sessions`、`overrides.clear` 被调、会话从 `_sessions`/`_sessions_by_id` 移除）、不支持路径返回 False；`can_delete`/`get_session_path` 行为。
- DeleteConfirmModal：构造/compose 冒烟 + pilot（y/Enter dismiss True，n/Esc dismiss False）。
- app pilot：搜索框聚焦下 ← 弹 DeleteConfirmModal、→ 弹 RenameModal；`_apply_delete` 接缝（mock search_engine）；`action_delete_session` 对不支持 agent 走 toast 不弹框；确认 `r` 不再绑定。

## 不做（YAGNI）

- 不支持批量删除、回收站/撤销。
- 不为非文件 agent（Crush/OpenCode/Copilot VSCode）实现删除。
- 不保留 `r` 绑定。

## 影响文件

- 修改：`adapters/base.py`、`adapters/crush.py`、`adapters/opencode.py`、`adapters/copilot_vscode.py`、`search.py`、`tui/modal.py`、`tui/styles.py`、`tui/app.py`、`README.md`
- 测试：`tests/test_*adapter*.py`（或新增 `tests/test_delete.py`）、`tests/test_search.py`、`tests/test_tui.py`
