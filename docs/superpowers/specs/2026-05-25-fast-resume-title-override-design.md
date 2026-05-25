# fast-resume 自定义标题（title override）设计

- 日期：2026-05-25
- 状态：已通过 brainstorming，待 writing-plans
- 目标仓库：`uniStark/fast-resume`（fork 自 `angristan/fast-resume`）

## 背景与问题

fast-resume 自身不存储标题。建索引时，各 adapter 实时从会话文件派生标题：

- `ClaudeAdapter` 取「第一条真实用户消息」作为标题，并刻意忽略 Claude 的 `summary` 字段（其注释说 summary 在 resume 后常常过时）。
- `CodexAdapter` 取第一条用户 prompt（80 字硬截断）。

因此标题是「每次重建索引时实时算出来的派生值」，没有任何可编辑、可持久化的标题字段。用户希望在 TUI 里快捷修改某条会话的标题，并且修改要在 `fr --rebuild` 之后依然保留。

## 关键约束

1. 自定义标题必须在 `fr --rebuild`、schema 升级后依然保留。
2. 不得改写各 agent 的原始会话文件（格式各异、有破坏原始记录与影响 agent 本身的风险）。
3. 自定义标题应当**可被搜索命中**——这是给会话改名的核心价值（改成好记的名字以便日后找到）。因此「生效标题」必须落在被索引的 `title` 字段里。
4. 必须能「清空自定义标题、恢复原始标题」。

## 采用方案

存储模型：**独立覆盖层**（brainstorming 中用户选定）。fast-resume 自己维护一份 `{session_id: 自定义标题}` 的覆盖表，建索引时在解析出的原始标题之上叠加。不碰 agent 原始文件，`--rebuild` 后自动重新叠加，可随时清除恢复。

## 详细设计

### 1. 存储层 —— 新增 `src/fast_resume/overrides.py`

- `TitleOverrides` 类，背后为 JSON 文件：`{session_id: "自定义标题"}`。
- 文件位置：**数据目录**而非 cache —— `~/.local/share/fast-resume/title_overrides.json`。
  - 理由：cache 目录（`~/.cache/fast-resume`，放 Tantivy 索引）语义上随时可清、清了能从源文件重建；自定义标题是不可重建的用户数据，不能与 cache 同生死。
  - 在 `config.py` 新增 `DATA_DIR = Path.home() / ".local" / "share" / "fast-resume"` 与 `TITLE_OVERRIDES_FILE = DATA_DIR / "title_overrides.json"`。
- 接口：
  - `get(session_id) -> str | None`
  - `set(session_id, title) -> None`
  - `clear(session_id) -> None`
  - `all() -> dict[str, str]`
- 写入采用原子写（写临时文件后 `os.replace`）。
- 容错：文件不存在视为空；JSON 损坏时记录日志并退化为空覆盖表，不崩溃。

### 2. 索引层 —— 叠加覆盖并保留原始标题

- `adapters/base.py` 的 `Session` dataclass 新增字段 `base_title: str = ""`（解析得到的原始标题）。
- `index.py` Tantivy schema 新增一个 **stored-only** 字段 `base_title`（不索引、仅存储）；现有 `title` 字段（已索引、可搜索）改为存「生效标题」。
- `SCHEMA_VERSION` 由 `20` 提升为 `21`，触发一次自动 rebuild（项目既有迁移套路即靠 bump 版本号）。
- 将 `add_sessions` 与 `update_sessions` 中重复的建文档逻辑抽取为私有 `_build_document(session) -> tantivy.Document`（顺带消除现有重复，因为正好在此处改动），统一逻辑：
  ```
  base = session.base_title or session.title
  effective = overrides.get(session.id) or base
  # 写入文档: title=effective, base_title=base, 其余字段不变
  ```
  幂等性：override 始终优先，重复建索引不会产生错误结果。
- `_doc_to_session` 读回时：`title = doc["title"]`（生效标题，用于显示与搜索），`base_title = doc["base_title"]`（原始标题）。
- `TantivyIndex` 持有一个 `TitleOverrides` 实例（构造时注入，便于测试）。

效果：
- `--rebuild`：adapter 产出新 session（`base_title` 为空 → 用解析标题当 base），覆盖自动重新叠加。
- 清空覆盖后，`effective = base`，原始标题还原。
- 搜索：`title` 字段存的是生效标题，故能命中自定义标题。

### 3. TUI 层 —— `r` 键弹框改名

- `tui/app.py` 新增 `Binding("r", "rename_session", "Rename")`（`r` 当前未占用，与既有键位 `/ enter c ctrl+\` tab j k ...` 不冲突）。
- 新增 `RenameModal`（复用现有 `tui/modal.py` 的 ModalScreen 模式），输入框预填当前标题，`Enter` 保存、`Esc` 取消。
- `action_rename_session()` 流程：
  1. 取当前选中行对应的 `Session`。
  2. 弹出 `RenameModal`，预填 `session.title`。
  3. 提交回调：
     - 输入非空 → `overrides.set(session.id, 新标题)`。
     - 输入清空 → `overrides.clear(session.id)`（恢复原始标题）。
  4. `index.update_sessions([session])` 落地到 Tantivy（搜索立即能命中新标题）。
  5. 更新内存中该 `Session` 的显示标题并刷新表格当前行。
- README 的 Keybindings 表格补一行：`r — Rename session title`。

### 4. 测试（遵循项目现有 TDD，先写测试）

- 新增 `tests/test_overrides.py`：`set/get/clear`、原子写、文件不存在、JSON 损坏容错。
- 扩展 `tests/test_index.py`：有覆盖时 `title` 为自定义且 `base_title` 为原始；清空后还原；搜索能命中自定义标题；`--rebuild`（schema 升级）后覆盖仍生效。
- 扩展 `tests/test_tui.py`：rename action 保存 / 清空恢复 / 取消三条路径。

## 不做（YAGNI）

- 不改写 agent 原始会话文件。
- 不提供批量改名、标签、分组等附加管理功能。
- 不为「清空恢复」走「重新解析源文件」的复杂路径——已用 `base_title` 字段以更简单的方式覆盖该需求。

## 影响文件清单

- 新增：`src/fast_resume/overrides.py`、`tests/test_overrides.py`
- 修改：`src/fast_resume/config.py`、`src/fast_resume/adapters/base.py`、`src/fast_resume/index.py`、`src/fast_resume/tui/app.py`、`src/fast_resume/tui/modal.py`（或新增 rename modal）、`README.md`、`tests/test_index.py`、`tests/test_tui.py`
