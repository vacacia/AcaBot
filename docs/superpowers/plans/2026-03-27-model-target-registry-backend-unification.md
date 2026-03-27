# Model Target Registry Backend Unification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AcaBot 当前分裂的模型消费入口彻底收成统一的 `model_provider / model_preset / model_target / model_binding` 后端体系，让 agent、compactor、image caption、LTM 和插件都只按 `model_target` 取模型，不再保留 `default_model / summary_model / 私有 preset_id` 旁路。

**Architecture:** 保留 filesystem-backed `model_provider / model_preset / model_binding` 真源，但把“谁在用模型”从松散的 `target_type + target_id` 字段和 profile/session 私有配置，升级成正式 `model_target` 目录。内建 target 由 runtime 固定注册，插件 target 由插件动态声明并注册到统一 target catalog；解析层统一从 `model_target -> model_binding -> RuntimeModelRequest + fallback_requests` 展开主模型和回退链。运行时模块不再保存模型字段，只保存职责位点或直接请求既定 target。

**Tech Stack:** Python 3.11、`yaml` filesystem registry、`litellm`、现有 `RuntimeHttpApiServer / RuntimeControlPlane / RuntimeConfigControlPlane`、Vue WebUI 最小同步。

---

## References

- Spec:
  - `/home/acacia/AcaBot/docs/superpowers/specs/2026-03-27-model-target-registry-and-core-simplemem-design.md`
- Current docs:
  - `/home/acacia/AcaBot/docs/13-model-registry.md`
  - `/home/acacia/AcaBot/docs/04-routing-and-profiles.md`
  - `/home/acacia/AcaBot/docs/08-webui-and-control-plane.md`
- Primary code:
  - `/home/acacia/AcaBot/src/acabot/runtime/model/model_registry.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/model/model_resolution.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/memory/context_compactor.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/inbound/image_context.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/plugin_manager.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/control/http_api.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/control/model_ops.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/control/config_control_plane.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/bootstrap/builders.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/bootstrap/loaders.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/contracts/routing.py`

## Assumptions Locked In

- 这是一次大刀阔斧的正向重构，不保留 `default_model / summary_model / summary_model_preset_id / model_preset_id` 作为正式解析旁路。
- `model_target` 是正式对象，但第一版不要求它 filesystem-backed；固定 system target 来自代码注册，`agent:<agent_id>` target 来自 live profile registry，插件 target 来自插件声明。
- `model_binding` 从这一版开始只对 `target_id` 生效，不再保留 `(target_type, target_id)` 双字段契约。
- `model_preset` 必须有能力类型，第一版至少区分 `chat` 和 `embedding`。
- 固定 system target 最少覆盖：
  - `system:compactor_summary`
  - `system:image_caption`
  - `system:ltm_extract`
  - `system:ltm_query_plan`
  - `system:ltm_answer`
  - `system:ltm_embed`
- `agent:<agent_id>` target 必须随着 profile load 和 reload 动态重建。
- 宿主只负责暴露 target 和解析结果；插件自己决定 target 未绑定时怎样报错。
- persisted plugin binding 在插件 target 尚未注册时允许进入“未解析”状态，不能因为这类 target 的延迟出现而阻断整个 runtime bootstrap。
- SessionConfig 不再承载模型选择；Session WebUI 里的 AI 模型字段必须退出正式契约。

## File Map

**Create**

- `src/acabot/runtime/model/model_targets.py`
  - 定义 `ModelTaskKind`、`ModelCapability`、`ModelTarget`、system target catalog、agent target builder、插件 target slot 声明和动态注册器。
- `tests/runtime/test_model_targets.py`
  - 覆盖内建 target、插件 target、能力匹配和 dynamic register/unregister 语义。

**Modify**

- `src/acabot/runtime/model/model_registry.py`
  - 给 `ModelPreset` 增加 `task_kind + capabilities`；给 `ModelBinding` 改成 `target_id + preset_ids` 形式；移除 legacy run/summary 解析旁路；接入 target catalog 校验和解析；对 `plugin:*` target 支持延迟解析状态；扩展 `ModelMutationResult` 和 control-plane snapshot，使 unresolved binding 有正式返回形状。
- `src/acabot/runtime/model/model_resolution.py`
  - 删除 profile-based fallback 解析；改成按 `agent:<agent_id>`、`system:compactor_summary`、`system:image_caption` 取模型。
- `src/acabot/runtime/model/model_agent_runtime.py`
  - 删除 `ctx.profile.default_model` 回落，只认 `ctx.model_request`。
- `src/acabot/runtime/memory/context_compactor.py`
  - 删除 `summary_model` legacy 字段和 fallback；改成只吃 `ctx.summary_model_request`。
- `src/acabot/runtime/inbound/image_context.py`
  - 删除 `caption_preset_id` 私有模型配置；改成固定请求 `system:image_caption`。
- `src/acabot/runtime/contracts/routing.py`
  - 从 `AgentProfile` 删除 `default_model`。
- `src/acabot/runtime/control/profile_loader.py`
  - 删除 profile 配置里的 `default_model` 归一化和导出逻辑。
- `src/acabot/runtime/bootstrap/loaders.py`
  - 停止从 config/profile 构造默认模型字段。
- `src/acabot/runtime/control/config_control_plane.py`
  - profile 读写和 reload 不再暴露 `default_model`；删除相关写回逻辑。
- `src/acabot/runtime/control/model_ops.py`
  - 暴露 `list_model_targets / get_model_target / preview_effective_target_model`；移除依赖 profile legacy 值的 preview；binding 的 list/get 返回带 `binding_state` 的 view snapshot。
- `src/acabot/runtime/control/control_plane.py`
  - 转发 target catalog API 和 target preview API。
- `src/acabot/runtime/control/http_api.py`
  - 增加 `/api/models/targets*` 接口；更新 binding payload 解析；binding list/get 返回 view snapshot；删除依赖旧字段的接口语义。
- `src/acabot/runtime/control/ui_catalog.py`
  - 增加 `model_task_kinds`、`model_capabilities`、`model_target_groups` 等目录选项；删除 binding target type 枚举。
- `src/acabot/runtime/plugin_manager.py`
  - 增加插件 `model_slots()` 声明协议；在 load/unload 生命周期里注册/注销插件 target，并在插件 target 变更后触发 model registry 重校验。
- `src/acabot/runtime/bootstrap/builders.py`
  - 构造共享 `ModelTargetCatalog` 并注入 model registry manager；删除 legacy 默认模型配置注入。
- `src/acabot/runtime/bootstrap/__init__.py`
  - 把 target catalog 传给 image context、plugin manager、control plane。
- `src/acabot/runtime/control/control_plane.py`
  - 如果有任何 profile -> model preview helper，改成 target-based preview。
- `src/acabot/runtime/app.py`
  - `_resolve_model_requests()` 改成 target-only 路径。
- `src/acabot/runtime/subagents/execution.py`
  - child run 模型解析改成 `agent:<delegate_agent_id>` target。
- `webui/src/views/SessionsView.vue`
  - 删除 Session AI 页里的主模型/摘要模型字段，避免 UI 继续写过期契约。
- `tests/runtime/test_model_registry.py`
- `tests/runtime/test_context_compactor.py`
- `tests/runtime/test_image_context.py`
- `tests/runtime/test_subagent_execution.py`
- `tests/runtime/test_bootstrap.py`
- `tests/runtime/test_webui_api.py`
- `tests/runtime/test_model_agent_runtime.py`
- `tests/runtime/test_builtin_skill_tools.py`
- `tests/runtime/test_builtin_tools.py`
- `tests/test_main.py`
  - 全部改成 target-based expectations，删除 legacy fallback 断言，并补齐 `AgentProfile.default_model` 删除后的构造器更新。
- `docs/13-model-registry.md`
- `docs/04-routing-and-profiles.md`
- `docs/08-webui-and-control-plane.md`
- `docs/HANDOFF.md`
  - 同步新的正式词典和迁移结果。

---

### Task 1: 建立 `model_target` 与 `task_kind + required_capabilities` 的正式后端对象

**Files:**
- Create: `src/acabot/runtime/model/model_targets.py`
- Modify: `src/acabot/runtime/model/model_registry.py`
- Modify: `src/acabot/runtime/control/ui_catalog.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_model_targets.py`
- Test: `tests/runtime/test_model_registry.py`

- [ ] **Step 1: 先写失败测试，锁定 target 和 `task_kind + required_capabilities` 契约**

```python
def test_model_target_catalog_rebuilds_agent_targets_from_profile_registry() -> None:
    catalog = MutableModelTargetCatalog(system_targets=SYSTEM_MODEL_TARGETS)
    catalog.replace_agent_targets(build_agent_model_targets([_profile("aca"), _profile("worker")]))

    aca = catalog.get("agent:aca")
    summary = catalog.get("system:compactor_summary")

    assert aca is not None
    assert aca.task_kind == "chat"
    assert summary is not None
    assert summary.allow_fallbacks is True
```

```python
async def test_model_registry_rejects_binding_when_preset_task_kind_mismatches_target(tmp_path: Path) -> None:
    manager = _manager(tmp_path, target_catalog=_catalog_with_embed_target())
    await manager.upsert_provider(_provider())
    await manager.upsert_preset(
        ModelPreset(
            preset_id="embed-a",
            provider_id="openai-main",
            model="text-embedding-3-large",
            task_kind="embedding",
            context_window=8192,
        )
    )

    result = await manager.upsert_binding(
        ModelBinding(binding_id="binding:summary", target_id="system:compactor_summary", preset_ids=["embed-a"])
    )

    assert result.ok is False
    assert "task_kind" in result.message
```

- [ ] **Step 2: 跑测试确认当前还没有这些对象**

Run:

```bash
pytest tests/runtime/test_model_targets.py tests/runtime/test_model_registry.py -q
```

Expected:

- `tests/runtime/test_model_targets.py` 因文件和对象不存在而失败。
- `test_model_registry.py` 因 `ModelBinding.target_id`、`ModelPreset.task_kind`、target catalog 校验不存在而失败。

- [ ] **Step 3: 实现 `ModelTarget` 与 `task_kind + capabilities` 版 `ModelPreset`**

```python
ModelTaskKind = Literal["chat", "embedding", "rerank", "speech_to_text", "text_to_speech", "image_generation"]
ModelCapability = Literal["tool_calling", "reasoning", "structured_output", "image_input", "image_output", "document_input", "audio_input", "audio_output", "video_input", "video_output"]


@dataclass(slots=True)
class ModelTarget:
    target_id: str
    task_kind: ModelTaskKind
    source_kind: Literal["system", "agent", "plugin"]
    owner_id: str
    description: str = ""
    required: bool = False
    allow_fallbacks: bool = True
    required_capabilities: list[ModelCapability] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass(slots=True)
class ModelPreset:
    preset_id: str
    provider_id: str
    model: str
    task_kind: ModelTaskKind
    capabilities: list[ModelCapability] = field(default_factory=list)
    context_window: int
    max_output_tokens: int | None = None
    model_params: dict[str, Any] = field(default_factory=dict)
```

Implementation notes:

- `ModelBinding` 改成：

```python
@dataclass(slots=True)
class ModelBinding:
    binding_id: str
    target_id: str
    preset_ids: list[str] = field(default_factory=list)
    timeout_sec: float | None = None
```

- 不再保留 `target_type / target_id / preset_id` 三件套混用结构。
- `model_targets.py` 里先落一份 system target catalog，并提供：
  - `replace_agent_targets()` 用于按 live profile registry 整批重建 `agent:<agent_id>`
  - `register_plugin_slots()` / `unregister_plugin_slots()` 用于维护插件 target
- `ui_catalog.py` 不再返回 `binding_target_types`，改成返回 `model_task_kinds`、`model_capabilities` 和 target group 信息。

- [ ] **Step 4: 让 registry 校验 binding 和 target/preset 能力是否匹配**

```python
target = self.target_catalog.get(binding.target_id)
if target is None:
    if binding.target_id.startswith("plugin:"):
        return ModelMutationResult(
            ok=True,
            applied=True,
            action="upsert",
            entity_type="binding",
            entity_id=binding.binding_id,
            binding_state="unresolved_target",
            message=f"plugin target not registered yet: {binding.target_id}",
        )
    raise ValueError(f"unknown model target: {binding.target_id}")
if not binding.preset_ids:
    raise ValueError(f"binding preset_ids is required: {binding.binding_id}")
for preset_id in binding.preset_ids:
    preset = self.presets.get(preset_id)
    if preset is None:
        raise ValueError(f"unknown preset_id for binding {binding.binding_id}: {preset_id}")
    if preset.task_kind != target.task_kind:
        raise ValueError(
            f"preset task_kind mismatch for {binding.binding_id}: "
            f"target={target.task_kind} preset={preset.task_kind}"
        )
    missing_capabilities = sorted(set(target.required_capabilities).difference(preset.capabilities))
    if missing_capabilities:
        raise ValueError(
            f"preset capabilities mismatch for {binding.binding_id}: "
            f"target={binding.target_id} missing={','.join(missing_capabilities)}"
        )
```

Implementation notes:

- unresolved plugin binding 必须能被持久化和列出，供 control plane 看到“已配置但 target 尚未注册”的状态。
- `agent:<agent_id>` target 缺失不属于可延迟情况；profile load/reload 后必须同步重建它们。

- [ ] **Step 5: 跑定向测试确认新对象和校验成立**

Run:

```bash
pytest tests/runtime/test_model_targets.py tests/runtime/test_model_registry.py -q
```

Expected:

- PASS。
- `test_model_registry.py` 不再出现 legacy fallback 路径断言。
- `plugin:*` binding 在插件未加载前会进入 unresolved 状态，而不是炸掉整个 registry reload。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/model/model_targets.py \
  src/acabot/runtime/model/model_registry.py \
  src/acabot/runtime/control/ui_catalog.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_model_targets.py \
  tests/runtime/test_model_registry.py
git commit -m "refactor: add model target catalog and task-kind bindings"
```

---

### Task 2: 把 runtime 模型解析收成 target-only 路径

**Files:**
- Modify: `src/acabot/runtime/model/model_resolution.py`
- Modify: `src/acabot/runtime/model/model_agent_runtime.py`
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
- Modify: `src/acabot/runtime/memory/context_compactor.py`
- Modify: `src/acabot/runtime/inbound/image_context.py`
- Test: `tests/runtime/test_context_compactor.py`
- Test: `tests/runtime/test_image_context.py`
- Test: `tests/runtime/test_subagent_execution.py`
- Test: `tests/runtime/test_bootstrap.py`

- [ ] **Step 1: 先写失败测试，锁定 target 解析和 legacy 退出**

```python
async def test_model_context_summarizer_uses_summary_target_request_without_legacy_summary_model(tmp_path: Path) -> None:
    manager = _manager_with_summary_target(tmp_path)
    request = manager.resolve_target_request("system:compactor_summary")

    assert request is not None
    assert request.binding_id == "binding:summary"
```

```python
async def test_image_context_service_uses_system_image_caption_target(tmp_path: Path) -> None:
    manager = _manager_with_image_caption_target(tmp_path)
    request = resolve_image_caption_request(manager)

    assert request is not None
    assert request.binding_id == "binding:image-caption"
```

```python
async def test_model_agent_runtime_requires_resolved_model_request() -> None:
    ctx = _ctx_without_model_request()

    result = await runtime.execute(ctx)

    assert result.error == "model_request is required"
```

```python
def test_record_only_run_skips_agent_target_resolution() -> None:
    request, snapshot = resolve_run_request_for_agent(
        _manager_with_agent_target(),
        run_mode="record_only",
        agent_id="aca",
    )

    assert request is None
    assert snapshot is None
```

- [ ] **Step 2: 跑测试确认当前还在吃 legacy 字段**

Run:

```bash
pytest \
  tests/runtime/test_context_compactor.py \
  tests/runtime/test_image_context.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- 因 `summary_model`、`caption_preset_id`、`ctx.profile.default_model` 仍在解析链里而失败。

- [ ] **Step 3: 把解析 helper 改成明确 target**

```python
def resolve_run_request_for_agent(
    manager: FileSystemModelRegistryManager | None,
    *,
    run_mode: str,
    agent_id: str,
):
    if manager is None:
        return None, None
    if run_mode == "record_only":
        return None, None
    request = manager.resolve_target_request(f"agent:{agent_id}")
    if request is None:
        return None, None
    return request, snapshot_from_runtime_request(request)
```

```python
def resolve_summary_request(manager: FileSystemModelRegistryManager | None):
    if manager is None:
        return None
    return manager.resolve_target_request("system:compactor_summary")
```

```python
def resolve_image_caption_request(manager: FileSystemModelRegistryManager | None):
    if manager is None:
        return None
    return manager.resolve_target_request("system:image_caption")
```

Implementation notes:

- 删除 `resolve_run_request(... explicit_profile_default_model ... effective_profile_default_model ...)` 这套 legacy 签名。
- 保留当前 `record_only` 语义：这种 run 不解析 agent model target，也不要求 target 有 binding。
- `ContextCompactionConfig.summary_model` 直接从 dataclass 和 builder 配置里删除。
- `ImageCaptionSettings.caption_preset_id` 删除，只保留功能开关和 prompt。
- `ModelAgentRuntime` 不再从 `ctx.profile.default_model` 回落；`ctx.model_request` 为空时直接返回错误。

- [ ] **Step 4: 更新 bootstrap / app / child run 的模型接线**

```python
model_request, model_snapshot = resolve_run_request_for_agent(
    self.model_registry_manager,
    run_mode=decision.run_mode,
    agent_id=profile.agent_id,
)
summary_model_request = resolve_summary_request(self.model_registry_manager)
```

Implementation notes:

- `RuntimeApp` 和 `LocalSubagentExecutionService` 都改成用 target-only helper。
- `build_context_compactor()` 不再从 config 读取 `summary_model`。
- `tests/runtime/test_bootstrap.py` 需要把 “summary_model config 进入 compactor” 的断言改成 “summary target 由 registry 负责”。

- [ ] **Step 5: 跑定向测试确认 target-only 解析跑通**

Run:

```bash
pytest \
  tests/runtime/test_context_compactor.py \
  tests/runtime/test_image_context.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- PASS。
- 没有任何测试再依赖 `summary_model`、`caption_preset_id`、`profile.default_model`。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/model/model_resolution.py \
  src/acabot/runtime/model/model_agent_runtime.py \
  src/acabot/runtime/app.py \
  src/acabot/runtime/subagents/execution.py \
  src/acabot/runtime/memory/context_compactor.py \
  src/acabot/runtime/inbound/image_context.py \
  tests/runtime/test_context_compactor.py \
  tests/runtime/test_image_context.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_bootstrap.py
git commit -m "refactor: resolve runtime models only from targets"
```

---

### Task 3: 从 profile/session/control plane 里彻底拔掉私有模型字段

**Files:**
- Modify: `src/acabot/runtime/contracts/routing.py`
- Modify: `src/acabot/runtime/control/profile_loader.py`
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/model_ops.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `webui/src/views/SessionsView.vue`
- Test: `tests/runtime/test_webui_api.py`
- Test: `tests/test_main.py`
- Test: `tests/runtime/test_model_agent_runtime.py`
- Test: `tests/runtime/test_builtin_skill_tools.py`
- Test: `tests/runtime/test_builtin_tools.py`
- Test: `tests/runtime/test_memory_broker.py`
- Test: `tests/runtime/test_app.py`
- Test: `tests/runtime/test_pipeline_runtime.py`
- Test: `tests/runtime/test_plugin_manager.py`
- Test: `tests/runtime/test_profile_loader.py`

- [ ] **Step 1: 先写失败测试，锁定 profile/session 不再暴露模型字段**

```python
async def test_profile_payload_no_longer_contains_default_model(base_url: str) -> None:
    profile = request_json(base_url, "/api/profiles/aca")

    assert "default_model" not in profile["data"]
```

```python
def test_agent_profile_contract_does_not_export_default_model() -> None:
    profile = AgentProfile(agent_id="aca", name="Aca", prompt_ref="prompt/default")

    assert not hasattr(profile, "default_model")
```

- [ ] **Step 2: 跑测试确认当前契约还没退出**

Run:

```bash
DEFAULT_MODEL_TESTS=$(rg -l "default_model=|default_model\"|summary_model" tests/runtime tests -S)
pytest \
  ${DEFAULT_MODEL_TESTS} \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_model_agent_runtime.py \
  tests/runtime/test_builtin_skill_tools.py \
  tests/runtime/test_builtin_tools.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_app.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_profile_loader.py \
  tests/test_main.py -q
```

Expected:

- 因 `default_model` 仍在 profile/control plane 里而失败。

- [ ] **Step 3: 删掉 `AgentProfile.default_model` 与 profile/config 写回逻辑**

```python
@dataclass(slots=True)
class AgentProfile:
    agent_id: str
    name: str
    prompt_ref: str
    enabled_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    computer_policy: ComputerPolicy | None = None
    config: dict[str, Any] = field(default_factory=dict)
```

Implementation notes:

- `build_profiles()` / `build_filesystem_profiles()` 不再读取任何默认模型字段。
- `_profile_to_config()` 不再回写 `default_model`。
- `upsert_profile()` 允许读写的 payload 里明确忽略模型字段。
- `SessionsView.vue` 的 AI 页去掉主模型/摘要模型下拉，只保留 prompt、tools、skills、context 策略。
- 动手前先 `rg -l "default_model=|default_model\"|summary_model" tests/runtime tests -S`，把所有直接构造 `AgentProfile(default_model=...)` 和旧 UI 断言一起收掉，不只改当前 task 列出的最小文件。
- 回归口径以这次 grep 的完整输出为准，不以 task 文件列表的最小集合为准。

- [ ] **Step 4: 把 control-plane API 升级成 target/binding 视角**

Implementation notes:

- 增加：
  - `GET /api/models/targets`
  - `GET /api/models/targets/<target_id>`
  - `GET /api/models/targets/<target_id>/effective`
- 删除或重定向旧的：
  - `preview_effective_agent_model(agent_id)`
  - `preview_effective_summary_model()`
- `RuntimeModelControlOps` 直接提供 `preview_effective_target_model(target_id)`。
- profile reload 完成后，要同步调用 `model_target_catalog.replace_agent_targets(...)`，确保 `agent:<agent_id>` 不会停留在过期集合里。
- persisted `ModelBinding` 继续保持纯存储对象；control plane 额外引入 `ModelBindingSnapshot` 这类派生 view，至少包含：
  - `binding`
  - `binding_state`
  - `target_present`
  - `message`
- `upsert_model_binding()` 继续返回 `ModelMutationResult`，但给它补 `binding_state` 字段，避免 unresolved plugin target 只能靠 message 猜。

- [ ] **Step 5: 跑定向测试确认 profile/session 契约收干净**

Run:

```bash
DEFAULT_MODEL_TESTS=$(rg -l "default_model=|default_model\"|summary_model" tests/runtime tests -S)
pytest \
  ${DEFAULT_MODEL_TESTS} \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_model_agent_runtime.py \
  tests/runtime/test_builtin_skill_tools.py \
  tests/runtime/test_builtin_tools.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_app.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_profile_loader.py \
  tests/test_main.py -q
```

Expected:

- PASS。
- WebUI API 返回的 profile 不再带 `default_model`。
- Session shell 前端不再保留过期模型字段。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/contracts/routing.py \
  src/acabot/runtime/control/profile_loader.py \
  src/acabot/runtime/bootstrap/loaders.py \
  src/acabot/runtime/control/config_control_plane.py \
  src/acabot/runtime/control/model_ops.py \
  src/acabot/runtime/control/control_plane.py \
  src/acabot/runtime/control/http_api.py \
  webui/src/views/SessionsView.vue \
  tests/runtime/test_webui_api.py \
  tests/test_main.py
git commit -m "refactor: remove private model fields from profile and session contracts"
```

---

### Task 4: 让插件通过 model slots 动态注册统一 target

**Files:**
- Modify: `src/acabot/runtime/plugin_manager.py`
- Modify: `src/acabot/runtime/model/model_targets.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/control/model_ops.py`
- Test: `tests/runtime/test_model_targets.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 先写失败测试，锁定插件 slot 注册语义**

```python
class DemoPlugin(RuntimePlugin):
    name = "demo"

    def model_slots(self) -> list[RuntimePluginModelSlot]:
        return [
            RuntimePluginModelSlot(
                slot_id="extractor",
                task_kind="chat",
                required=True,
                allow_fallbacks=True,
                description="demo extractor",
            )
        ]
```

```python
async def test_plugin_manager_registers_plugin_model_targets() -> None:
    catalog = MutableModelTargetCatalog(system_targets=[])
    manager = RuntimePluginManager(..., model_target_catalog=catalog)

    await manager.load_plugin(DemoPlugin())

    target = catalog.get("plugin:demo:extractor")
    assert target is not None
    assert target.source_kind == "plugin"
```

```python
async def test_plugin_binding_can_stay_unresolved_until_plugin_slot_registers(tmp_path: Path) -> None:
    manager = _model_registry_manager(tmp_path, target_catalog=MutableModelTargetCatalog(system_targets=[]))
    await manager.upsert_provider(_provider())
    await manager.upsert_preset(_chat_preset())

    result = await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:demo",
            target_id="plugin:demo:extractor",
            preset_ids=["chat-main"],
        )
    )

    assert result.ok is True
    assert result.binding_state == "unresolved_target"
```

- [ ] **Step 2: 跑测试确认当前插件系统还没有模型槽位概念**

Run:

```bash
pytest tests/runtime/test_model_targets.py tests/runtime/test_webui_api.py -q
```

Expected:

- 因 `model_slots()`、plugin target catalog 注册逻辑不存在而失败。

- [ ] **Step 3: 扩 RuntimePlugin 协议并接进 plugin 生命周期**

```python
@dataclass(slots=True)
class RuntimePluginModelSlot:
    slot_id: str
    task_kind: ModelTaskKind
    required: bool = False
    allow_fallbacks: bool = True
    required_capabilities: list[ModelCapability] = field(default_factory=list)
    description: str = ""
```

```python
class RuntimePlugin(ABC):
    def model_slots(self) -> list[RuntimePluginModelSlot]:
        return []
```

Implementation notes:

- `RuntimePluginManager.__init__()` 注入 `model_target_catalog`。
- `load_plugin()` 成功后，把 `plugin:<plugin.name>:<slot_id>` 注册到 catalog。
- `unload_plugins()` / `teardown_all()` 里同步注销这些 target。
- 这一步不要让插件直接接触 `model_registry_manager`，只负责声明 slot。
- persisted `plugin:*` bindings 在 slot 尚未注册时只进入 unresolved，不让 bootstrap 因此失败。
- 插件 load/unload 后要触发 model registry revalidation，让 unresolved binding 能转成 resolved。

- [ ] **Step 4: 暴露 target 列表给 control plane**

Implementation notes:

- `RuntimeModelControlOps.list_model_targets()` 返回内建 + 插件动态 target 的稳定列表。
- `/api/models/targets` 返回分组信息，供后续 UI 选择器使用。
- `/api/models/bindings` 和 `/api/models/bindings/<id>` 返回 `ModelBindingSnapshot`，明确带出 unresolved state，避免控制面误把“插件未加载”看成“绑定丢了”。

- [ ] **Step 5: 跑定向测试确认插件 target 真能进统一后端**

Run:

```bash
pytest tests/runtime/test_model_targets.py tests/runtime/test_webui_api.py -q
```

Expected:

- PASS。
- 插件加载后能在 target 列表里看到 `plugin:<plugin_id>:<slot_id>`。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/plugin_manager.py \
  src/acabot/runtime/model/model_targets.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/control/model_ops.py \
  tests/runtime/test_model_targets.py \
  tests/runtime/test_webui_api.py
git commit -m "feat: register plugin model slots as unified targets"
```

---

### Task 5: 文档和回归收尾

**Files:**
- Modify: `docs/13-model-registry.md`
- Modify: `docs/04-routing-and-profiles.md`
- Modify: `docs/08-webui-and-control-plane.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: 更新模型文档词典和正式解析链**

```md
- `model_provider`
- `model_preset`
- `model_target`
- `model_binding`
```

```md
正式解析路径:
`model_target -> model_binding -> RuntimeModelRequest + fallback_requests`
```

- [ ] **Step 2: 更新 routing/profile/session 文档**

Implementation notes:

- 删除 `profile.default_model`、Session AI 模型字段的描述。
- 写清楚 profile 和 session 不再承担模型真源职责。

- [ ] **Step 3: 更新 HANDOFF**

Write three sentences only:

```md
模型系统已经改成 `model_target` 驱动，agent/summary/image caption/LTM/插件统一从 binding 取模型。
profile、session 和插件私有模型字段已经退出正式契约，后续不要再往这些对象里塞 model id。
如果后续加新的模型消费者，先加 target，再接 binding，再写调用方；不要绕过 resolver。
```

- [ ] **Step 4: 跑整组模型相关回归**

Run:

```bash
DEFAULT_MODEL_TESTS=$(rg -l "default_model=|default_model\"|summary_model" tests/runtime tests -S)
pytest \
  ${DEFAULT_MODEL_TESTS} \
  tests/runtime/test_model_targets.py \
  tests/runtime/test_model_registry.py \
  tests/runtime/test_context_compactor.py \
  tests/runtime/test_image_context.py \
  tests/runtime/test_subagent_execution.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_model_agent_runtime.py \
  tests/runtime/test_builtin_skill_tools.py \
  tests/runtime/test_builtin_tools.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_app.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_plugin_manager.py \
  tests/runtime/test_profile_loader.py \
  tests/test_main.py -q
```

Expected:

- PASS。
- 没有任何失败再提到 `default_model`、`summary_model`、`summary_model_preset_id`。

- [ ] **Step 5: Commit**

```bash
git add \
  docs/13-model-registry.md \
  docs/04-routing-and-profiles.md \
  docs/08-webui-and-control-plane.md \
  docs/HANDOFF.md
git commit -m "docs: rewrite model registry around targets and bindings"
```

---

## Exit Criteria

- `ModelBinding` 只绑定 `target_id`，不再绑定 `(target_type, target_id)`。
- runtime 内部所有模型消费者都只认 `model_target`。
- `AgentProfile`、Session shell、image caption、compactor 都不再保留私有模型字段。
- 插件可以声明 `model_slots()`，并在统一 target catalog 里出现。
- 所有模型调用的 fallback 链都来自 `model_binding`，没有模块私有 fallback 配置。
