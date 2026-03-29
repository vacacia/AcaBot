# Subagent Filesystem Catalog and Session Visibility Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 subagent 的定义真源改成文件系统 catalog，并把实际可见性严格收口到 session 的 `visible_subagents`，同时删掉 plugin 注册 subagent 的错误关系，保留“plugin 提供 tool，tool 可分配给 subagent”这一条唯一交点。

**Architecture:** 第一版只做四件事：`SUBAGENT.md` 文件发现与 catalog、`SUBAGENT.md -> prompt/model` 接线、session 级可见性、child run 执行边界。subagent 继续是受限 child run，但它的定义不再来自 profile 或 plugin，而是来自文件系统；session 只声明“当前能看到谁”。这一版明确不做 resume、最近消息自动注入、后台任务和 skill 式资源目录；同时明确禁止 subagent child run 进入审批态，避免 approval replay 变相形成“可继续子会话”。

**Tech Stack:** Python, pytest, runtime bootstrap, filesystem catalogs, session-config, ToolBroker, builtin tools, RuntimePluginManager

---

## Current Understanding

这一节不是实现步骤，而是这份计划立足的正式理解。后面的所有改造都以这组口径为准。

### 什么是 subagent

- `subagent` 是 runtime 内建的内部 worker。
- 它不是 plugin，不是普通函数型 tool，也不是单独对外说话的前台角色。
- `delegate_subagent` 只是前台发起委派的 builtin tool 入口，不是 subagent 本体。
- 真正的 subagent 是一个受限 child run：它有自己的 prompt、自己的工具集、自己的 world 可见性和自己的结果回传。

### subagent 定义真源属于文件系统

- “系统里有哪些 subagent 存在”这件事，正式真源是文件系统。
- 每个 subagent 只有一份定义文件，不做 skill 式的 `references/ scripts/ assets/` 资源目录。
- 推荐目录形状是：

```text
.agents/subagents/
  excel-worker/
    SUBAGENT.md
  search-worker/
    SUBAGENT.md
```

- `SUBAGENT.md` 负责描述：
  - `name`
  - `description`
  - `tools`
  - 可选 `model_target`
  - 正文 prompt

### subagent 可见性属于 session

- `subagent` 的可见性直接挂在 `session` 身上。
- session 负责声明“当前前台能看到哪些 subagent”。
- session 不负责保存 subagent prompt 和工具定义，只负责 allowlist。
- runtime 判断“这次能不能委派给某个 subagent”时，只认当前 session 和当前 run 的实际可见性。

### 是否委派是运行时判断，不是配置 rule

- session 配置只回答“能看到谁”。
- 当前前台到底要不要调用 subagent，是运行时临场判断。
- 第一版不做“命中某个 case 自动 handoff”的配置规则。

### 第一版默认不递归

- subagent child run 默认不能再调用 `delegate_subagent`。
- 所以第一版不需要循环检测和深度控制。
- 最稳定的做法就是：child run 看不到 delegation tool，也没有可见 subagent 列表。

### plugin 和 subagent 的关系

- plugin 和 subagent 没有直接关系。
- plugin 不注册 subagent，不提供 subagent，不参与 subagent 生命周期，也不决定 subagent 可见性。
- 它们唯一的交点是：
  - plugin 可以提供 tool
  - tool 可以分配给 subagent

### 暂时不做的东西

- 不做 subagent resume
- 不做“继续上一个 subagent”的稳定会话身份
- 不做最近消息自动注入
- 不做后台任务管理
- 不做 skill 式资源目录
- 不做原始 `model=gpt-xxx` 这类直接模型字符串解析

### 为什么暂时不做 resume

- 当前 run 机制把每次 child run 当成独立执行实例。
- run 私有的 tool loop、中间消息和结果默认不会自动变成可继续的共享子会话状态。
- 要支持 resume，需要先重新定义 subagent 的稳定身份和历史保存边界。
- 这不是当前这轮重构的主目标。

### 为什么第一版要禁掉 subagent 审批

- 当前 generic approval replay 会把 `waiting_approval` 的 run 当普通 run 继续恢复。
- 如果 subagent child run 也能进入 `waiting_approval`，那它就会绕出一条“先卡审批，后续继续”的隐式续跑路径。
- 这和当前“不做 resume”的目标冲突。
- 所以第一版要明确规定：subagent child run 一旦命中需要审批的工具，直接失败，不进入 `waiting_approval`。

---

## File Structure

### Subagent 文件系统 catalog

- Create: `src/acabot/runtime/subagents/package.py`
  - 定义 `SubagentPackageManifest`、`SubagentPackageDocument`、frontmatter 解析。
- Create: `src/acabot/runtime/subagents/loader.py`
  - 递归发现 `SUBAGENT.md`，支持 project/user 扫描根。
- Create: `src/acabot/runtime/subagents/catalog.py`
  - 像 `SkillCatalog` 一样维护发现结果与同名覆盖规则。
- Modify: `src/acabot/runtime/subagents/__init__.py`
  - 导出新 catalog / loader / package 类型。
- Modify: `src/acabot/runtime/bootstrap/config.py`
  - 增加 `resolve_subagent_catalog_dirs(...)`。
- Modify: `src/acabot/runtime/bootstrap/builders.py`
  - 构造 `SubagentCatalog`，不再把 local profile 自动当成 subagent executor。
- Modify: `src/acabot/runtime/bootstrap/components.py`
  - 把 `subagent_catalog` 收进 runtime 组件快照。
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
  - 正式接线 `SubagentCatalog`。
- Create: `tests/runtime/test_subagent_catalog.py`
  - 覆盖文件发现、project/user 覆盖、文档读取。

### `SUBAGENT.md` 到 prompt/model 的运行时接线

- Modify: `src/acabot/runtime/bootstrap/loaders.py`
  - 把 subagent prompt 文本接进现有 prompt loader 链，而不是绕开 `PromptLoader`。
- Modify: `src/acabot/runtime/control/config_control_plane.py`
  - reload 配置时同步刷新 subagent prompt overlay。
- Modify: `src/acabot/runtime/model/model_resolution.py`
  - 支持优先解析 `profile.config["model_target"]`，不要强制只走 `agent:{agent_id}`。
- Modify: `src/acabot/runtime/subagents/execution.py`
  - synthetic child profile 默认继承 `agent:{parent_agent_id}` 的模型目标；如果 `SUBAGENT.md` 指定 `model_target`，则显式覆盖。
- Modify: `tests/runtime/test_subagent_execution.py`
  - 覆盖 subagent prompt 正文和 model target 的接线结果。

### Session 级 subagent 可见性

- Modify: `src/acabot/runtime/contracts/session_config.py`
  - 给 `ComputerPolicyDecision` 增加 `visible_subagents`。
- Modify: `src/acabot/runtime/control/session_loader.py`
  - 支持 session 文件里的 `visible_subagents`。
- Modify: `src/acabot/runtime/control/session_runtime.py`
  - 把 `visible_subagents` 解析进 run 级 computer 决策。
- Modify: `tests/runtime/test_session_config_models.py`
  - 固定 `visible_subagents` 契约。
- Modify: `tests/runtime/test_session_runtime.py`
  - 固定 session 文件对 `visible_subagents` 的解析。

### Delegation 执行边界

- Modify: `src/acabot/runtime/subagents/contracts.py`
  - 把 delegation request 从“直接按 executor registry 查 id”收成“带 session allowlist 和 catalog 解析结果的正式请求”。
- Modify: `src/acabot/runtime/subagents/broker.py`
  - 按当前 session allowlist + catalog 做 resolve，不再按 registry 裸查。
- Modify: `src/acabot/runtime/subagents/execution.py`
  - 从 `SubagentCatalog` 读取定义，构造 child run 使用的临时运行配置。
- Modify: `src/acabot/runtime/builtin_tools/subagents.py`
  - 把当前 run 的 `visible_subagents` 显式传给 broker。
- Modify: `src/acabot/runtime/tool_broker/contracts.py`
  - 在工具上下文里显式带上 run 级 `visible_subagents`。
- Modify: `src/acabot/runtime/tool_broker/broker.py`
  - 只暴露当前 session 真正可见的 subagent 摘要和 `delegate_subagent`。
- Modify: `tests/runtime/test_subagent_delegation.py`
  - 把旧的“注册了就能调”改成“session 开了才准调”。
- Modify: `tests/runtime/test_subagent_execution.py`
  - 固定 child run 默认禁递归，并覆盖 filesystem subagent 执行。
- Create: `tests/runtime/test_subagent_session_visibility.py`
  - 覆盖 prompt 摘要与执行拒绝路径。
- Modify: `src/acabot/runtime/approval_resumer.py`
  - 明确 child run 不走 approval replay 主线。
- Modify: `tests/runtime/test_subagent_execution.py`
  - 覆盖 subagent child run 命中审批时直接失败，不进入 `waiting_approval`。

### Plugin 解耦

- Modify: `src/acabot/runtime/plugin_manager.py`
  - 删除 plugin 注册 subagent executor 的入口和上下文。
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
  - 去掉 plugin manager 对 subagent delegator 的错误挂接。
- Modify: `src/acabot/runtime/__init__.py`
  - 删除退役导出。
- Modify: `tests/runtime/runtime_plugin_samples.py`
  - 删除 `SampleDelegationWorkerPlugin`。
- Modify: `tests/runtime/test_plugin_manager.py`
  - 去掉 plugin 注册 subagent 的测试。
- Modify: `tests/runtime/test_ops_control_plugin.py`
  - 去掉 sample plugin subagent 依赖。
- Delete: `tests/runtime/test_subagent_delegation_plugin.py`

### Control Plane / API / WebUI 收口

- Modify: `src/acabot/runtime/control/snapshots.py`
  - 把 `SubagentExecutorSnapshot` 收成 catalog 视角的 `SubagentSnapshot`。
- Modify: `src/acabot/runtime/control/control_plane.py`
  - 从 `SubagentCatalog` 列出 subagent，而不是从 executor registry 列出 executor。
- Modify: `src/acabot/runtime/control/http_api.py`
  - 把 subagent 列表接口收成 catalog 语义。
- Modify: `src/acabot/runtime/plugins/ops_control.py`
  - `/subagents` 命令展示 catalog subagent，而不是 executor。
- Modify: `src/acabot/runtime/control/config_control_plane.py`
  - reload runtime configuration 时刷新 `SubagentCatalog`，不再重建 `runtime:local_profile` executors。
- Modify: `webui/src/views/SubagentsView.vue`
  - 前端页面改成展示 catalog subagent。
- Modify: `tests/runtime/test_webui_api.py`
  - WebUI/API 测试改成 catalog 语义。

### 文档

- Modify: `docs/00-ai-entry.md`
- Modify: `docs/19-tool.md`
- Modify: `docs/20-subagent.md`
- Modify: `docs/15-known-issues-and-design-gaps.md`
- Modify: `docs/HANDOFF.md`

---

## Task 1: 建立 `SubagentCatalog` 文件系统真源

**Files:**
- Create: `src/acabot/runtime/subagents/package.py`
- Create: `src/acabot/runtime/subagents/loader.py`
- Create: `src/acabot/runtime/subagents/catalog.py`
- Modify: `src/acabot/runtime/subagents/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/config.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Test: `tests/runtime/test_subagent_catalog.py`
- Test: `tests/runtime/test_bootstrap.py`

- [ ] **Step 1: 写失败测试，锁定 `SUBAGENT.md` 的基本形状**

```python
def test_filesystem_subagent_loader_discovers_subagent_documents(tmp_path: Path) -> None:
    root = tmp_path / ".agents" / "subagents" / "excel-worker"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SUBAGENT.md").write_text(
        """---
name: excel-worker
description: Handle excel cleanup
tools:
  - read
  - bash
model_target: agent:aca
---
You are an excel cleanup worker.
""",
        encoding="utf-8",
    )

    loader = FileSystemSubagentPackageLoader([SubagentDiscoveryRoot(host_root_path=str(tmp_path / ".agents" / "subagents"))])
    manifests = loader.discover()

    assert [item.subagent_name for item in manifests] == ["excel-worker"]
    assert manifests[0].description == "Handle excel cleanup"
```

```python
def test_subagent_catalog_prefers_project_over_user(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: 运行测试，确认当前还没有 subagent 文件系统 catalog**

Run:
```bash
pytest tests/runtime/test_subagent_catalog.py -q
```

Expected: FAIL，缺少 loader / catalog / package 相关实现。

- [ ] **Step 3: 实现最小文件系统 catalog**

约定：

- 扫描根目录默认值：
  - `./.agents/subagents`
  - `~/.agents/subagents`
- 每个 subagent 目录只认 `SUBAGENT.md`
- 只解析 frontmatter + 正文 prompt
- 不支持 `references/ scripts/ assets/`
- `model_target` 只接受现有 model registry 能解析的 target id

最小 manifest 形状：

```python
@dataclass(slots=True)
class SubagentPackageManifest:
    subagent_name: str
    scope: str
    host_subagent_file_path: str
    description: str
    tools: list[str]
    model_target: str | None = None
```

- [ ] **Step 4: 把 bootstrap 接到 `SubagentCatalog`**

Run:
```bash
pytest tests/runtime/test_subagent_catalog.py tests/runtime/test_bootstrap.py -q
```

Expected: PASS，新 catalog 能被 runtime 组装并暴露出来；这一步同时把 bootstrap 里仍然写死 local profile executor 的旧断言一起改掉，避免后面任务顺序被旧测试绊住。

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/subagents/package.py \
  src/acabot/runtime/subagents/loader.py \
  src/acabot/runtime/subagents/catalog.py \
  src/acabot/runtime/subagents/__init__.py \
  src/acabot/runtime/bootstrap/config.py \
  src/acabot/runtime/bootstrap/builders.py \
  src/acabot/runtime/bootstrap/components.py \
  src/acabot/runtime/bootstrap/__init__.py \
  tests/runtime/test_subagent_catalog.py
git commit -m "feat: add filesystem subagent catalog"
```

## Task 2: 把 `SUBAGENT.md` prompt/model 接到现有执行链

**Files:**
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/model/model_resolution.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
- Modify: `tests/runtime/test_subagent_execution.py`

- [ ] **Step 1: 写失败测试，固定 prompt/model 接线**

```python
async def test_delegate_subagent_uses_subagent_prompt_body(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["sample_configured_tool"],
        model_target="agent:aca",
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(...)

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={"delegate_agent_id": "excel-worker", "task": "整理表格"},
        ctx=_tool_ctx(...),
    )

    assert result.raw["ok"] is True
    assert "You are Excel Worker." in components.agent.calls[-1]["system_prompt"]
```

```python
async def test_delegate_subagent_uses_manifest_model_target_override(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: 运行测试，确认当前执行链还只认 profile/prompt_ref/agent target**

Run:
```bash
pytest tests/runtime/test_subagent_execution.py -q
```

Expected: FAIL，当前 child run 还不能直接消费 `SUBAGENT.md` 的 prompt body 和 `model_target`。

- [ ] **Step 3: 给 subagent 建 prompt overlay 和 model target override**

关键调整：

- `build_prompt_loader()` 把 catalog 文档正文接成一层静态 `PromptLoader`
- synthetic child profile 使用 `prompt_ref="subagent/<name>"`
- `resolve_model_requests_for_profile()` 先看 `profile.config["model_target"]`
- synthetic child profile 默认设置：
  - `model_target = manifest.model_target`
  - 否则回退到 `agent:{parent_agent_id}`

临时运行配置至少要有：

```python
AgentProfile(
    agent_id=f"subagent:{document.manifest.subagent_name}",
    name=document.manifest.subagent_name,
    prompt_ref=f"subagent/{document.manifest.subagent_name}",
    enabled_tools=list(document.manifest.tools),
    config={"model_target": resolved_model_target},
)
```

- [ ] **Step 4: 运行测试，确认 child run 已经使用文件系统定义**

Run:
```bash
pytest tests/runtime/test_subagent_execution.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/bootstrap/loaders.py \
  src/acabot/runtime/control/config_control_plane.py \
  src/acabot/runtime/model/model_resolution.py \
  src/acabot/runtime/subagents/execution.py \
  tests/runtime/test_subagent_execution.py
git commit -m "refactor: wire subagent prompt and model sources"
```

## Task 3: 把 subagent 执行定义从 local profile / executor registry 切到 catalog

**Files:**
- Modify: `src/acabot/runtime/subagents/contracts.py`
- Modify: `src/acabot/runtime/subagents/broker.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `tests/runtime/test_subagent_execution.py`
- Modify: `tests/runtime/test_subagent_delegation.py`

- [ ] **Step 1: 写失败测试，固定“subagent 来自 catalog，不来自 profile 自动注册”**

```python
async def test_bootstrap_no_longer_registers_local_profiles_as_subagents() -> None:
    components = build_runtime_components(...)

    assert not hasattr(components, "subagent_executor_registry")
```

```python
async def test_delegate_subagent_resolves_catalog_subagent_not_local_profile() -> None:
    ...
```

- [ ] **Step 2: 运行测试**

Run:
```bash
pytest tests/runtime/test_subagent_execution.py tests/runtime/test_subagent_delegation.py tests/runtime/test_bootstrap.py -q
```

Expected: FAIL，旧实现仍依赖 `runtime:local_profile`。

- [ ] **Step 3: 改 broker 和 execution，按 catalog resolve**

关键调整：

- broker 先用 `SubagentCatalog` 解析 `delegate_agent_id`
- execution 从 `SubagentPackageDocument` 构造 child run 所需的 synthetic profile
- 不再把 local profile 自动注册成 subagent executor

- [ ] **Step 4: 运行测试**

Run:
```bash
pytest tests/runtime/test_subagent_execution.py tests/runtime/test_subagent_delegation.py tests/runtime/test_bootstrap.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/subagents/contracts.py \
  src/acabot/runtime/subagents/broker.py \
  src/acabot/runtime/subagents/execution.py \
  src/acabot/runtime/bootstrap/builders.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_subagent_delegation.py \
  tests/runtime/test_bootstrap.py
git commit -m "refactor: resolve subagents from filesystem catalog"
```

## Task 4: 收口 session 级 `visible_subagents`

**Files:**
- Modify: `src/acabot/runtime/contracts/session_config.py`
- Modify: `src/acabot/runtime/control/session_loader.py`
- Modify: `src/acabot/runtime/control/session_runtime.py`
- Test: `tests/runtime/test_session_config_models.py`
- Test: `tests/runtime/test_session_runtime.py`

- [ ] **Step 1: 写失败测试，锁定 `visible_subagents` 契约**

```python
def test_computer_policy_decision_keeps_visible_subagents() -> None:
    decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        visible_subagents=["excel-worker", "search-worker"],
    )

    assert decision.visible_subagents == ["excel-worker", "search-worker"]
```

```python
def test_session_runtime_reads_visible_subagents_from_computer_block(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: 运行测试**

Run:
```bash
pytest tests/runtime/test_session_config_models.py tests/runtime/test_session_runtime.py -q
```

Expected: FAIL，当前 computer 决策还没有这个正式字段。

- [ ] **Step 3: 实现 session-config 到 run decision 的传递**

最小形状：

```python
class ComputerPolicyDecision:
    ...
    visible_skills: list[str] | None = None
    visible_subagents: list[str] = field(default_factory=list)
```

inline default session 的 `visible_subagents` 默认值必须是空列表。

- [ ] **Step 4: 运行测试**

Run:
```bash
pytest tests/runtime/test_session_config_models.py tests/runtime/test_session_runtime.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/contracts/session_config.py \
  src/acabot/runtime/control/session_loader.py \
  src/acabot/runtime/control/session_runtime.py \
  tests/runtime/test_session_config_models.py \
  tests/runtime/test_session_runtime.py
git commit -m "refactor: add session visible subagents"
```

## Task 5: 把 delegation 暴露和执行严格绑定到当前 session

**Files:**
- Modify: `src/acabot/runtime/tool_broker/contracts.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `src/acabot/runtime/builtin_tools/subagents.py`
- Modify: `src/acabot/runtime/subagents/broker.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `tests/runtime/test_context_assembler.py`
- Create: `tests/runtime/test_subagent_session_visibility.py`
- Modify: `tests/runtime/test_subagent_execution.py`
- Modify: `tests/runtime/test_subagent_delegation.py`

- [ ] **Step 1: 写失败测试，固定“session 开了才可见、才可调用”**

```python
async def test_delegate_subagent_hidden_when_session_visible_subagents_is_empty() -> None:
    ...
```

```python
async def test_delegate_subagent_rejects_target_not_in_session_allowlist() -> None:
    ...
```

```python
async def test_subagent_child_run_hides_delegate_subagent() -> None:
    ...
```

```python
async def test_non_default_frontstage_agent_can_delegate_when_session_allows_it() -> None:
    ...
```

- [ ] **Step 2: 运行测试**

Run:
```bash
pytest \
  tests/runtime/test_context_assembler.py \
  tests/runtime/test_subagent_session_visibility.py \
  tests/runtime/test_subagent_execution.py -q
```

Expected: FAIL，旧实现还会按 registry 暴露 subagent。

- [ ] **Step 3: 改 ToolBroker 和 builtin tool**

原则：

- prompt 摘要只展示当前 session allowlist 里且 catalog 可解析的 subagent
- `delegate_subagent` 只有当前 session 可见 subagent 非空时才暴露
- builtin tool 执行时，把当前 run 的 `visible_subagents` 传给 broker
- 删除 default-agent-only gate，让非默认前台 agent 也能按 session allowlist 使用 subagent

- [ ] **Step 4: 在 child run 里写死禁递归**

```python
ComputerPolicyDecision(
    actor_kind="subagent",
    ...,
    visible_subagents=[],
)
```

第一版不允许 subagent 再看到任何 delegation 入口。

- [ ] **Step 5: 子任务命中审批时直接失败**

规则：

- subagent child run 一旦命中需要 approval 的工具
- 直接返回错误
- 不进入 `waiting_approval`
- 不让 generic approval replay 接管 child run

需要补测试：

```python
async def test_subagent_child_run_cannot_enter_waiting_approval() -> None:
    ...
```

- [ ] **Step 6: 运行测试**

Run:
```bash
pytest \
  tests/runtime/test_context_assembler.py \
  tests/runtime/test_subagent_session_visibility.py \
  tests/runtime/test_subagent_execution.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add \
  src/acabot/runtime/tool_broker/contracts.py \
  src/acabot/runtime/tool_broker/broker.py \
  src/acabot/runtime/builtin_tools/subagents.py \
  src/acabot/runtime/subagents/broker.py \
  src/acabot/runtime/subagents/execution.py \
  tests/runtime/test_context_assembler.py \
  tests/runtime/test_subagent_session_visibility.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_subagent_delegation.py
git commit -m "refactor: enforce session scoped subagent delegation"
```

## Task 6: 删除 plugin 注册 subagent 的错误路径，并保留 plugin tool 交点

**Files:**
- Modify: `src/acabot/runtime/plugin_manager.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `tests/runtime/runtime_plugin_samples.py`
- Modify: `tests/runtime/test_plugin_manager.py`
- Modify: `tests/runtime/test_ops_control_plugin.py`
- Modify: `tests/runtime/test_subagent_execution.py`
- Modify: `tests/runtime/test_tool_broker.py`
- Delete: `tests/runtime/test_subagent_delegation_plugin.py`

- [ ] **Step 1: 写失败测试，锁定正确关系**

```python
async def test_runtime_plugin_manager_keeps_plugin_tools_after_subagent_api_removal() -> None:
    ...
```

```python
async def test_subagent_can_use_plugin_tool_when_subagent_definition_enables_it() -> None:
    ...
```

- [ ] **Step 2: 运行测试**

Run:
```bash
pytest \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_ops_control_plugin.py \
  tests/runtime/test_subagent_delegation_plugin.py \
  tests/runtime/test_tool_broker.py \
  tests/runtime/test_subagent_execution.py -q
```

Expected: FAIL，旧 plugin API 仍然暴露 subagent executor 能力。

- [ ] **Step 3: 删除 plugin/subagent 直接耦合**

删除这些东西：

- `RuntimePlugin.subagent_executors()`
- `SubagentExecutorRegistration`
- plugin manager 里的 subagent executor 注册/卸载
- `attach_subagent_delegator()` 这类只为错误关系服务的接线
- `SampleDelegationWorkerPlugin`

保留：

- plugin 正常注册 hook
- plugin 正常注册 tool
- subagent 通过普通 `enabled_tools` 使用 plugin tool

这一段属于公开 API 的硬切：

- `RuntimePlugin.subagent_executors()`
- `RuntimePluginContext.subagent_delegator`
- 对应 runtime 顶层导出

这三块都直接删除，不保留兼容层。

- [ ] **Step 4: 删除旧测试并跑回归**

Run:
```bash
git rm tests/runtime/test_subagent_delegation_plugin.py
pytest \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_ops_control_plugin.py \
  tests/runtime/test_tool_broker.py \
  tests/runtime/test_subagent_execution.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/plugin_manager.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/runtime_plugin_samples.py \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_ops_control_plugin.py \
  tests/runtime/test_tool_broker.py \
  tests/runtime/test_subagent_execution.py
git commit -m "refactor: remove plugin subagent registration"
```

## Task 7: 把 control plane / API / WebUI 从 executor 语义切到 catalog 语义

**Files:**
- Modify: `src/acabot/runtime/control/snapshots.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `src/acabot/runtime/plugins/ops_control.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `webui/src/views/SubagentsView.vue`
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `tests/runtime/test_ops_control_plugin.py`

- [ ] **Step 1: 写失败测试，固定“对外展示的是 catalog subagent，不是 executor”**

```python
async def test_control_plane_lists_catalog_subagents() -> None:
    ...
```

```python
async def test_webui_subagents_endpoint_returns_catalog_items() -> None:
    ...
```

- [ ] **Step 2: 运行测试**

Run:
```bash
pytest \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_ops_control_plugin.py -q
```

Expected: FAIL，当前控制面和 UI 还在看 executor 列表。

- [ ] **Step 3: 改控制面与页面**

原则：

- control plane 正式列出 `SubagentCatalog`
- `/subagents` 或现有子接口都返回 catalog 语义
- ops `/subagents` 命令展示 subagent 名称和描述
- reload runtime configuration 时刷新 catalog，不再重建 `runtime:local_profile`

- [ ] **Step 4: 运行测试**

Run:
```bash
pytest \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_ops_control_plugin.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/control/snapshots.py \
  src/acabot/runtime/control/control_plane.py \
  src/acabot/runtime/control/http_api.py \
  src/acabot/runtime/plugins/ops_control.py \
  src/acabot/runtime/control/config_control_plane.py \
  webui/src/views/SubagentsView.vue \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_ops_control_plugin.py
git commit -m "refactor: expose subagent catalog in control plane"
```

## Task 8: 更新文档与交接文件

**Files:**
- Modify: `docs/00-ai-entry.md`
- Modify: `docs/19-tool.md`
- Modify: `docs/20-subagent.md`
- Modify: `docs/15-known-issues-and-design-gaps.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: 更新文档口径**

需要写清：

- subagent 定义真源是文件系统
- 每个 subagent 只有 `SUBAGENT.md`
- session 只负责 `visible_subagents`
- child run 默认不递归
- plugin 和 subagent 的唯一交点是 tool 分配
- 当前不支持 resume

- [ ] **Step 2: 更新 `HANDOFF`**

只写三句话：

1. subagent 定义真源已经从 profile/plugin 方向收成文件系统 catalog。
2. session 只负责 `visible_subagents`，delegation 执行严格认当前 run allowlist。
3. 第一版默认不递归，也不支持 resume，plugin 与 subagent 只通过 tool 交叉。

- [ ] **Step 3: 跑最终回归**

Run:
```bash
pytest \
  tests/runtime/test_subagent_catalog.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_session_config_models.py \
  tests/runtime/test_session_runtime.py \
  tests/runtime/test_subagent_delegation.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_subagent_session_visibility.py \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_ops_control_plugin.py \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_tool_broker.py \
  tests/runtime/test_context_assembler.py -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add \
  docs/00-ai-entry.md \
  docs/19-tool.md \
  docs/20-subagent.md \
  docs/15-known-issues-and-design-gaps.md \
  docs/HANDOFF.md
git commit -m "docs: align subagent filesystem catalog design"
```

## Notes

- 这轮重构不做兼容层，直接删掉 plugin 注册 subagent 的旧入口。
- 这轮重构不做 subagent resume；如果以后要做，先单独写新的 session identity 设计。
- 这轮重构不做最近消息自动注入；让主 agent 自己把调用 prompt 描述清楚。
- `SubagentCatalog` 和 `SkillCatalog` 只统一“文件系统管理方式”，不统一语义和资源形状。
- 这轮重构里 `SUBAGENT.md` 的模型字段只支持 `model_target`，不支持直接写裸模型字符串。
- 这轮重构要求 subagent child run 不进入审批态，避免 approval replay 形成隐式续跑。
