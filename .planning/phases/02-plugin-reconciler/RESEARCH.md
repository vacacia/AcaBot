# Phase 02 — Plugin Reconciler: Research Findings

## 1. Current plugin_manager.py Deep Audit

### 文件概览

`src/acabot/runtime/plugin_manager.py` — 959 行, 包含以下组成部分:

| 区域 | 行号 | 内容 |
|------|------|------|
| HookPoint | L51-156 | `RuntimeHookPoint` (Enum), `RuntimeHookResult`, `RuntimeHook` (ABC), `RuntimeHookRegistry` |
| Plugin 协议 | L160-302 | `RuntimePluginSpec`, `RuntimeToolRegistration`, `RuntimePluginContext`, `RuntimePlugin` (ABC) |
| Manager | L306-853 | `RuntimePluginManager` 主体 |
| Config loading | L857-959 | `parse_runtime_plugin_spec`, `load_runtime_plugin`, `load_runtime_plugins_from_config[_with_failures]` |

### RuntimePluginManager 关键行为

**构造函数** (L329-391):
- 接收 `config`, `gateway`, `tool_broker`, `sticky_notes`, `computer_runtime`, `skill_catalog`, `control_plane`, `model_target_catalog`, `builtin_plugins`, `plugins`
- `_builtin_plugins` / `_builtin_plugin_names` / `_builtin_plugin_types` 三重追踪 builtin 插件
- `_pending` 队列 = `_fresh_builtin_plugins()` + 用户传入 `plugins`
- `failed_plugin_import_paths: list[str]` 追踪导入失败的路径

**ensure_started()** (L502-529):
- 双检锁 (asyncio.Lock + _started flag)
- 构造单个 `RuntimePluginContext`, 所有 pending 插件共用同一个 context
- 遍历 pending 逐个调 `load_plugin()`

**load_plugin()** (L531-631) — 核心加载流程:
1. 去重检查: `plugin.name in self._names`
2. 构造或使用传入的 `RuntimePluginContext`
3. 调 `plugin.setup(context)` — 异常则跳过
4. Model target 注册: `model_target_catalog.register_plugin_slots(plugin_id=plugin.name, slots=plugin.model_slots())` (L578-597)
   - 注册后立即 `_revalidate_model_registry()` (调 `control_plane.reload_models()`)
   - 失败则 rollback: `unregister_plugin_targets()` + 再次 revalidate + `teardown()`
5. 注册 hooks: `plugin.hooks()` 返回 `list[tuple[RuntimeHookPoint, RuntimeHook]]`, 逐个 `self.hooks.register(point, hook)`
6. 注册 runtime_tools: `plugin.runtime_tools()` 返回 `list[RuntimeToolRegistration]`, 每个调 `tool_broker.register_tool(spec, handler, source=f"plugin:{plugin.name}")`
7. 注册 legacy tools: `plugin.tools()` 返回 `list[ToolDef]`, 每个调 `tool_broker.register_legacy_tool(tool, source=f"plugin:{plugin.name}")`
8. 加入 `self.loaded`, `self._names`

**run_hooks()** (L633-664):
- 从 `self.hooks.get(point)` 取已启用 hooks (按 priority 排序)
- 逐个 `await hook.handle(ctx)`, 异常记日志继续
- `skip_agent` 短路返回

**unload_plugins()** (L666-713):
- 逆序遍历 `self.loaded`
- 对每个匹配的插件: `tool_broker.unregister_source(f"plugin:{plugin.name}")` → `teardown()` → `unregister_plugin_targets()`
- 重建 `self.loaded`, `self._names`
- 调 `_rebuild_hook_registry()` — 从头重建整个 registry
- 触发 `_revalidate_model_registry()`

**teardown_all()** (L724-762):
- 逆序遍历, 对每个: unregister tools → teardown() → unregister model targets
- 清空所有内部状态, _started = False
- 触发 revalidate

**reload_from_config()** (L764-840):
- 全量: `teardown_all()` → 重建 pending → `ensure_started()`
- 选择性: `unload_plugins(requested_names)` → 重新导入实例 → `load_plugin()` 每个

**RuntimeHookRegistry** (L104-154):
- `_hooks: dict[RuntimeHookPoint, list[RuntimeHook]]`
- `register()` 追加到列表并按 `priority` 排序
- `get()` 过滤 `enabled=False` 的 hook

### RuntimePluginContext 当前字段 (L188-226)

```python
@dataclass(slots=True)
class RuntimePluginContext:
    config: Config                           # 全局配置对象
    gateway: GatewayProtocol
    tool_broker: ToolBroker
    sticky_notes: StickyNoteService | None
    computer_runtime: ComputerRuntime | None
    skill_catalog: SkillCatalog | None
    control_plane: RuntimeControlPlane | None

    def get_plugin_config(self, plugin_name: str) -> dict[str, object]:
        return dict(self.config.get_plugin_config(plugin_name))
```

ADR 改造点:
- `config: Config` → `plugin_config: dict[str, Any]` (只给插件自己的配置)
- 新增 `plugin_id: str`, `data_dir: Path`
- 删除 `get_plugin_config()` 方法
- ADR 中提到 `reference_backend: ReferenceBackend | None` 需删除 (D-02, 该字段当前不存在于代码中, 已经是正确状态)

### 必须保留的行为

1. **Hook priority 排序 + enabled 过滤** — `RuntimeHookRegistry.register()` 和 `.get()`
2. **skip_agent 短路** — `run_hooks()` L661-662
3. **单 hook 异常不影响其他** — L654-659
4. **Tool source 命名空间: `plugin:{plugin_name}`** — L609, L618, L686
5. **逆序 teardown** — L740
6. **Model target 注册 + revalidate + rollback** — L578-597
7. **去重检查** — L555-557

---

## 2. Integration Point Mapping

### 直接 import plugin_manager 的文件

| 文件 | 行号 | 导入内容 | 用途 |
|------|------|----------|------|
| `plugins/ops_control.py` | L27 | `RuntimeHook, RuntimeHookPoint, RuntimeHookResult, RuntimePlugin, RuntimePluginContext` | 插件实现 |
| `plugins/napcat_tools.py` | L28 | `RuntimePlugin, RuntimePluginContext` | 插件实现 |
| `plugins/backend_bridge_tool.py` | L11 | `RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration` | 插件实现 |
| `bootstrap/__init__.py` | L39-44 | `RuntimePlugin, RuntimePluginManager, load_runtime_plugins_from_config, load_runtime_plugins_from_config_with_failures` | DI 装配 |
| `bootstrap/builders.py` | L35 | `RuntimePlugin` | `build_builtin_runtime_plugins()` 返回类型 |
| `bootstrap/components.py` | L28 | `RuntimePluginManager` | `RuntimeComponents.plugin_manager` 字段类型 |
| `app.py` | L36 | `RuntimePluginManager` | `RuntimeApp.plugin_manager` 字段类型 |
| `pipeline.py` | L32, L455 | `RuntimeHookPoint, RuntimePluginManager`, `RuntimeHookResult` | `plugin_manager` 字段 + `run_hooks()` |
| `control/control_plane.py` | L44 | `RuntimePluginManager` | `plugin_manager` 字段 + `_list_loaded_plugins()` |
| `control/config_control_plane.py` | L36 | `RuntimePluginManager, RuntimePluginSpec, load_runtime_plugin` | `replace_plugin_configs()` + `_probe_plugin_import_error()` |
| `__init__.py` | L228-241 | 全部公开符号 re-export | Facade |

### 间接引用 (通过 `__init__.py` facade)

| 文件 | 导入 | 使用的符号 |
|------|------|-----------|
| `tests/runtime/test_plugin_manager.py` | `from acabot.runtime import ...` | `RuntimeHook, RuntimeHookPoint, RuntimeHookResult, RuntimePlugin, RuntimePluginContext, RuntimePluginManager, RuntimePluginModelSlot, load_runtime_plugins_from_config` |
| `tests/runtime/test_ops_control_plugin.py` | `from acabot.runtime import build_runtime_components` | 间接依赖整个 bootstrap |

### HTTP API 端点 (http_api.py)

当前 4 个插件相关端点:

| 端点 | 方法 | 行号 | 调用 |
|------|------|------|------|
| `/api/plugins` | GET | ~L312-314 | `control_plane.get_status()` → `loaded_plugins` |
| `/api/plugins/reload` | POST | ~L315-322 | `control_plane.reload_plugins()` |
| `/api/system/plugins/config` | GET | ~L334-335 | `control_plane.list_plugin_configs()` |
| `/api/system/plugins/config` | PUT | ~L336-342 | `control_plane.replace_plugin_configs()` |

---

## 3. ToolBroker Integration

### Tool 注册

`ToolBroker.register_tool()` (`broker.py` L63-79):
- 参数: `spec: ToolSpec`, `handler: ToolHandler`, `source: str`, `metadata: dict`
- 内部存储: `self._tools: dict[str, RegisteredTool]`
- `RegisteredTool` 包含 `source` 字段

`ToolBroker.register_legacy_tool()` (`broker.py` ~L100-122):
- 将 `ToolDef` 适配成 `register_tool()` 调用

### Tool 注销

`ToolBroker.unregister_source()` (`broker.py` L124-131):
```python
def unregister_source(self, source: str) -> list[str]:
    removed: list[str] = []
    for tool_name, registered in list(self._tools.items()):
        if registered.source != source:
            continue
        removed.append(tool_name)
        del self._tools[tool_name]
    return removed
```

**Source 命名约定**: `f"plugin:{plugin.name}"` — 例如 `plugin:ops_control`, `plugin:backend_bridge_tool`

这个约定在新体系中需保持一致: `f"plugin:{plugin_id}"`

---

## 4. Model Target Registration

### MutableModelTargetCatalog (model_targets.py)

**register_plugin_slots()** (L260-301):
- 参数: `plugin_id: str`, `slots: Iterable[RuntimePluginModelSlot]`
- 生成 target_id 格式: `f"plugin:{plugin_id}:{slot.slot_id}"`
- 写入 `self._plugin_targets: dict[str, ModelTarget]`
- 每个 slot 校验 task_kind 和 capabilities
- 冲突检查: 不允许覆盖非 plugin 来源的 target

**unregister_plugin_targets()** (L303-313):
- 按 `f"plugin:{plugin_id}:"` 前缀匹配删除

**Revalidation 行为** (plugin_manager.py L842-851):
```python
async def _revalidate_model_registry(self) -> None:
    if self.control_plane is None:
        return
    snapshot = await self.control_plane.reload_models()
    if snapshot.ok:
        return
    raise ValueError(snapshot.error or "model registry reload failed")
```

**Rollback 流程** (plugin_manager.py L586-597):
1. `register_plugin_slots()` 成功
2. `_revalidate_model_registry()` 失败
3. `unregister_plugin_targets(plugin.name)` 回滚
4. 再次 `_revalidate_model_registry()` 清理
5. `plugin.teardown()` 清理插件状态
6. 该插件不进入 loaded 列表

Host 的 `load_plugin()` 必须保留完全相同的 rollback 逻辑.

---

## 5. Plugin Capability Gap Audit (D-07)

### ADR 已知的 4 个缺口

1. **LLM 调用** — 插件需要统一 model service, 不直接碰 litellm
2. **定时任务** — 注册定时/周期性任务, 框架自动取消
3. **富消息发送** — Gateway 不支持构造 IM 原生消息组件
4. **平台适配器 API** — 群列表/成员信息/头像/文件上传

### 审计发现的额外缺口

**5. 事件订阅 (Event Subscription)**
- 当前 hook 体系绑定 pipeline 6 个固定点 (ON_EVENT, PRE_AGENT, POST_AGENT, BEFORE_SEND, ON_SENT, ON_ERROR)
- 没有独立的事件总线. 插件无法订阅 "所有群消息" 或 "notice 类型事件" 等细粒度事件
- 现有 OpsControlPlugin 通过 PRE_AGENT hook + 自行检查 event 类型绕过, 但这不是正式的事件订阅

**6. 插件间通信 (Inter-Plugin Communication)**
- 没有插件发现或消息传递机制
- 当前插件数量少 (3 个), 不紧急
- 如果后续有插件需要共享状态, 可通过 ToolBroker 的已注册工具间接调用, 或引入简单的 event bus

**7. 生命周期事件扩展**
- 当前只有 `setup()` 和 `teardown()`
- 缺少: `on_config_changed()` (配置变更通知), `health_check()` (健康探测)
- 本轮 reconciler 的 "先 unload 再 load" 模式等效于 config_changed, 但插件自身没有精细的 diff 感知

**8. 资源限制**
- 无内存/CPU/文件描述符隔离
- 无执行超时 (setup/teardown 可以无限阻塞)
- 本轮暂不需要, 单操作者场景插件数量可控

**9. 插件依赖声明**
- 没有 `depends_on` 字段
- 加载顺序是字母序, 没有显式依赖图
- 当前不需要, 但后续如果有 "插件 A 注册 tool 给插件 B 用" 的场景, 需要加

**10. 健康检查**
- StatusStore 的 `phase` 只反映加载时刻的状态
- 运行中如果插件内部出错 (如外部服务断连), 没有机制把 phase 更新为 unhealthy
- 可以在后续加入 `RuntimePlugin.health_check()` 可选协议方法

**结论**: 本轮只需要实现 ADR 已定义的内容. 以上 5-10 全部是 "记录方向, 不进本轮" 的能力.

---

## 6. WebUI Patterns

### 现有视图结构

```
webui/src/views/
  HomeView.vue
  PluginsView.vue      ← 当前 105 行, 需要完全重写
  SessionsView.vue
  ProvidersView.vue
  ModelsView.vue
  PromptsView.vue
  SkillsView.vue
  SubagentsView.vue
  SoulView.vue
  StickyNotesView.vue
  LtmConfigView.vue
  SystemView.vue
  AdminsView.vue
  LogsView.vue
```

### API Client (webui/src/lib/api.ts)

统一的 API 调用库:
- `apiGet<T>(path)` — GET with 15s 内存缓存 + localStorage 持久化缓存
- `apiPut<T>(path, body)` — PUT, 自动失效关联缓存
- `apiPost<T>(path, body)` — POST, 自动失效关联缓存
- `apiDelete<T>(path)` — DELETE, 自动失效关联缓存
- `peekCachedGet<T>(path)` — 同步读缓存, 用于初始渲染

所有 API 返回统一格式: `{ ok: boolean, data: T, error?: string }`

缓存失效映射 (api.ts L146-148):
```typescript
if (path.startsWith("/api/system/plugins/config") || path.startsWith("/api/plugins/reload")) {
    return ["/api/system/plugins/config", "/api/status"]
}
```

新端点需要更新这个缓存失效映射.

### 路由 (router.ts)

```typescript
{ path: "/config/plugins", name: "plugins", component: PluginsView }
```

路由路径不变, 只替换组件内容.

### 当前 PluginsView.vue 分析 (105 行)

- 调 `GET /api/system/plugins/config` 加载列表
- 每项显示: enabled checkbox + display_name + name + import path
- 保存按钮调 `PUT /api/system/plugins/config`
- 重载按钮调 `POST /api/plugins/reload`
- **没有** schema 驱动表单, 没有展开面板, 没有状态徽章

### 其他 View 的通用模式

观察 ProvidersView / ModelsView 等:
- `onMounted()` 调 `apiGet()` 加载初始数据
- `ref()` 管理列表和编辑状态
- 内联表单编辑 (不跳转)
- 保存后用返回值更新本地状态
- 使用 `ds-*` CSS class 系统 (ds-page, ds-hero, ds-list, ds-primary-button 等)

### 组件库

```
webui/src/components/    ← 存在但内容未审计
```

无第三方 UI 组件库 (无 Element/Ant/Vuetify). 全部用原生 HTML + 自定义 `ds-*` 样式.

---

## 7. Test Coverage

### 现有测试文件

**`tests/runtime/test_plugin_manager.py`** (549 行):

| 测试用例 | 覆盖行为 |
|----------|----------|
| `test_runtime_plugin_manager_registers_tools_and_lifecycle` | setup/teardown 调用次数, tool 注册, plugin config 读取 |
| `test_runtime_plugin_manager_registers_plugin_model_targets` | model target 注册 + unload 后注销 |
| `test_runtime_plugin_manager_rolls_back_plugin_targets_when_registry_reload_fails` | model target rollback: revalidate 失败 → unregister → teardown |
| `test_runtime_plugin_manager_unload_keeps_state_consistent_when_registry_reload_fails` | unload 时 revalidate 失败, 内部状态仍保持一致 |
| `test_thread_pipeline_can_be_short_circuited_by_runtime_plugin` | PRE_AGENT hook skip_agent 短路 |
| `test_load_runtime_plugins_from_config_supports_import_paths` | config 导入路径解析 |
| `test_runtime_plugin_manager_reload_clears_old_tools_and_reloads` | 全量 reload 清理旧 tools 并重新注册 |
| `test_runtime_plugin_manager_can_reload_selected_plugins_only` | 选择性 reload 不影响其他插件 |
| `test_runtime_plugin_manager_selected_reload_updates_failed_import_paths` | failed_import_paths 正确更新 |
| `test_runtime_plugin_manager_selected_reload_keeps_builtin_plugins` | builtin 插件在选择性 reload 中保留 |

**`tests/runtime/test_ops_control_plugin.py`**:
- 通过 `build_runtime_components()` 集成测试 OpsControlPlugin
- 本轮删除 OpsControlPlugin 后, 此测试文件也删除

**`tests/runtime/runtime_plugin_samples.py`**:
- 提供 `SampleConfiguredRuntimePlugin`, `AnotherConfiguredRuntimePlugin` 测试样本
- reload 测试依赖这些样本

### 测试 Fake 对象

- `FakeGateway` (从 test_outbox.py 导入)
- `FakeMessageStore` (从 test_outbox.py 导入)
- `FakeAgent`, `FakeAgentResponse` (从 _agent_fakes.py)

### conftest.py

```python
_plugins_dir = str(pathlib.Path(__file__).resolve().parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)
```

当前把 `plugins/` 加入 sys.path. ADR 要求改为 `extensions/`:
```python
_extensions_dir = str(pathlib.Path(__file__).resolve().parent.parent / "extensions")
```

### 新测试方向

1. `test_plugin_package.py` — PackageCatalog scan + manifest 解析 + 错误处理
2. `test_plugin_spec.py` — SpecStore load/save/delete + 原子写 + 错误处理
3. `test_plugin_status.py` — StatusStore load/save/delete
4. `test_plugin_runtime_host.py` — load/unload/teardown + hook 管理 + tool 注册
5. `test_plugin_reconciler.py` — reconcile_all / reconcile_one 的各种状态转换
6. 保留并适配: pipeline skip_agent 测试, model target rollback 测试

---

## 8. BackendBridgeToolPlugin Transition

### 当前文件 (`plugins/backend_bridge_tool.py`)

```python
from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
```

需要改为:
```python
from ..plugin_protocol import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
```

### 当前 bootstrap 注册方式

`bootstrap/builders.py` L67-73:
```python
def build_builtin_runtime_plugins(_agents=None) -> list[RuntimePlugin]:
    return [BackendBridgeToolPlugin()]
```

`bootstrap/__init__.py` L330:
```python
builtin_plugins = build_builtin_runtime_plugins()
```

然后传入 `RuntimePluginManager(builtin_plugins=builtin_plugins)`.

### ADR 方案

BackendBridgeToolPlugin 不走新插件体系. Bootstrap 直接实例化并手动注册 tool 到 ToolBroker:

```python
# bootstrap 中
bridge_plugin = BackendBridgeToolPlugin()
await bridge_plugin.setup(context)
for reg in bridge_plugin.runtime_tools():
    tool_broker.register_tool(reg.spec, reg.handler, source="builtin:backend_bridge")
```

或者更干净: 直接在 bootstrap 中构造 tool spec + handler, 不经过 RuntimePlugin 协议. 但 ADR 选择保留文件并标注为过渡期死代码.

### 其他依赖

- `BackendBridgeToolPlugin` 还依赖: `ToolBroker.backend_bridge` (L28), `BackendBridge` (L9), `BackendRequest`/`BackendSourceRef` (L10)
- 这些依赖不受插件体系重构影响

---

## 9. Bootstrap Integration Analysis

### 当前 build_runtime_components() 中的插件相关流程

`bootstrap/__init__.py` L330-355:

```python
# 1. 构造 builtin plugins
builtin_plugins = build_builtin_runtime_plugins()

# 2. 加载配置插件 (或使用注入的)
failed_plugin_import_paths: list[str] = []
configured_plugins = plugins
if configured_plugins is None:
    configured_plugins, failed_plugin_import_paths = load_runtime_plugins_from_config_with_failures(config)

# 3. 构造 RuntimePluginManager
runtime_plugin_manager = plugin_manager or RuntimePluginManager(
    config=config,
    gateway=gateway,
    tool_broker=runtime_tool_broker,
    sticky_notes=runtime_sticky_notes,
    computer_runtime=runtime_computer_runtime,
    skill_catalog=runtime_skill_catalog,
    model_target_catalog=runtime_model_registry_manager.target_catalog,
    builtin_plugins=builtin_plugins,
    plugins=configured_plugins,
)

# 4. 同步更新字段 (覆盖可能过时的引用)
runtime_plugin_manager.config = config
runtime_plugin_manager.gateway = gateway
# ... 多个字段赋值 ...

# 5. 注入 control_plane (循环依赖打破)
runtime_plugin_manager.attach_control_plane(control_plane)
runtime_plugin_manager.attach_computer_runtime(runtime_computer_runtime)
```

### 新体系 bootstrap 需要做的

```python
# 1. 构造 catalog / stores
catalog = PackageCatalog(extensions_plugins_dir)
spec_store = SpecStore(runtime_config_plugins_dir)
status_store = StatusStore(runtime_data_plugins_dir)

# 2. 构造 Host
host = PluginRuntimeHost(
    tool_broker=runtime_tool_broker,
    model_target_catalog=runtime_model_registry_manager.target_catalog,
)

# 3. 构造 context_factory 闭包
def context_factory(plugin_id, plugin_config):
    data_dir = runtime_data_plugins_dir / plugin_id / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return RuntimePluginContext(
        plugin_config=plugin_config,
        plugin_id=plugin_id,
        data_dir=data_dir,
        gateway=gateway,
        tool_broker=runtime_tool_broker,
        sticky_notes=runtime_sticky_notes,
        computer_runtime=runtime_computer_runtime,
        skill_catalog=runtime_skill_catalog,
        control_plane=None,  # 后补
    )

# 4. 构造 Reconciler
reconciler = PluginReconciler(catalog, spec_store, status_store, host, context_factory)

# 5. BackendBridgeToolPlugin 直接注册
bridge_plugin = BackendBridgeToolPlugin()
# ... 手动注册 tool ...
```

### 路径解析

目录路径需要从 config 解析, 不能硬编码:

- `extensions_plugins_dir`: 项目根 / `extensions/plugins/` (基于 Dockerfile PYTHONPATH 约定)
- `runtime_config_plugins_dir`: `runtime_config/plugins/` (跟随 `runtime.filesystem.base_dir`)
- `runtime_data_plugins_dir`: `runtime_data/plugins/` (跟随 `runtime.runtime_root`)

需要对齐 `bootstrap/config.py` 中的 `resolve_runtime_path()` 和 `resolve_filesystem_path()`.

---

## 10. app.py Lifecycle Integration

### 当前 start() (L115-136)

```python
async def start(self):
    await self.recover_active_runs()
    await self._ensure_plugins_started()    # 调 plugin_manager.ensure_started()
    try:
        if self.long_term_memory_ingestor:
            await self.long_term_memory_ingestor.start()
        self.install()
        await self.gateway.start()
    except Exception:
        # 清理: ltm ingestor stop + plugin_manager.teardown_all()
        raise
```

### 新体系

```python
async def start(self):
    await self.recover_active_runs()
    await self.reconciler.reconcile_all()    # 替代 ensure_plugins_started
    try:
        ...
    except Exception:
        await self.host.teardown_all()       # 替代 plugin_manager.teardown_all()
        raise
```

### 当前 stop() (L138-160)

```python
async def stop(self):
    await self.gateway.stop()
    if self.plugin_manager:
        await self.plugin_manager.teardown_all()
    if self.long_term_memory_ingestor:
        await self.long_term_memory_ingestor.stop()
```

新体系: `self.plugin_manager.teardown_all()` → `self.host.teardown_all()`

### handle_event() 中的 _ensure_plugins_started (L196)

当前: `await self._ensure_plugins_started()` 在每次事件进入时检查

新体系: 不需要这个幂等检查, reconcile_all 在 start() 中一次性完成. 可以删除 `_ensure_plugins_started()`.

---

## 11. Pipeline Integration

### 当前 hook 调用 (pipeline.py)

| 位置 | 行号 | Hook Point |
|------|------|-----------|
| execute() 开头 | L118 | `ON_EVENT` |
| agent 调用前 | L211 | `PRE_AGENT` |
| agent 调用后 | L229 | `POST_AGENT` |
| outbox dispatch 前 | L235 | `BEFORE_SEND` |
| outbox dispatch 后 | L241 | `ON_SENT` |
| 异常处理 | L257 | `ON_ERROR` |

### _run_plugin_hooks (L443-458)

```python
async def _run_plugin_hooks(self, point, ctx):
    if self.plugin_manager is None:
        from .plugin_manager import RuntimeHookResult
        return RuntimeHookResult()
    return await self.plugin_manager.run_hooks(point, ctx)
```

新体系改为:
```python
async def _run_plugin_hooks(self, point, ctx):
    if self.plugin_runtime_host is None:
        from .plugin_protocol import RuntimeHookResult
        return RuntimeHookResult()
    return await self.plugin_runtime_host.run_hooks(point, ctx)
```

字段从 `plugin_manager: RuntimePluginManager` 改为 `plugin_runtime_host: PluginRuntimeHost`.

---

## 12. Config Control Plane — 待删除的方法

`config_control_plane.py` 中需要删除的方法:

| 方法 | 行号 | 原因 |
|------|------|------|
| `list_plugin_configs()` | L775-806 | 依赖旧的 `runtime.plugins` 配置列表 |
| `replace_plugin_configs()` | L808-834 | 依赖旧的 `runtime.plugins` 配置写回 |
| `_probe_plugin_import_error()` | L837-851 | 依赖 `load_runtime_plugin()` |
| `_plugin_name_from_path()` | L854-867 | 从 import path 提取名字 |
| `_plugin_display_name_from_path()` | L870-885 | 美化 import path |

`reload_runtime_configuration()` (L235-275) 中的插件相关部分:
```python
if self.plugin_manager is not None:
    builtin_plugins = self.builtin_plugin_factory() if ...
    await self.plugin_manager.replace_builtin_plugins(builtin_plugins)
    await self.plugin_manager.reload_from_config()
```

这段需要改为: 调 `reconciler.reconcile_all()` 或不在这里触发 (让 API handler 自己决定).

---

## 13. Control Plane — 待修改的方法

`control_plane.py`:

| 方法 | 行号 | 变更 |
|------|------|------|
| `reload_plugins()` | L183-198 | 删除, 被 `reconcile_all_plugins()` 替代 |
| `_list_loaded_plugins()` | L1041-1050 | 数据源从 `plugin_manager.loaded` 改为 `host.loaded_plugin_ids()` |
| `list_plugin_configs()` | L462-467 | 删除, 被 `list_plugins()` 替代 |
| `replace_plugin_configs()` | L469-475 | 删除, 被 `update_plugin_spec()` 替代 |

新增方法 (业务逻辑在 control_plane, API 在 http_api):
- `list_plugins() -> list[PluginView]`
- `get_plugin(plugin_id) -> PluginView | None`
- `update_plugin_spec(plugin_id, enabled, config) -> PluginView`
- `delete_plugin_spec(plugin_id) -> PluginView`
- `reconcile_all_plugins() -> list[PluginView]`

---

## 14. extensions/plugins/ 当前状态

```
extensions/plugins/
  napcat_tools/      ← 空目录 (只有 __pycache__)
  notepad/           ← 空目录
```

两个空目录都需要删除. 本轮完成后 `extensions/plugins/` 存在但为空.

---

## 15. Summary of Key Design Decisions

| 决策 | 选择 | 原因 |
|------|------|------|
| D-01 | 不做配置迁移 | 旧 `config.yaml` 里的 `runtime.plugins` 列表视为不存在 |
| D-02 | ADR 中 `reference_backend` 字段不需要修 | 当前代码已经没有这个字段 |
| D-03 | WebUI 用 inline state + toast | 简单可靠 |
| D-04 | Badge + modal 展示错误 | failed 状态需要显示 load_error |
| D-05 | PUT spec → 返回更新后视图 | 两步刷新: 提交 + 用返回值更新 |
| D-06 | 发布 sample 插件模板 | 帮助开发者理解 plugin.yaml 格式 |
| D-07 | 缺口 5-10 记录但不进本轮 | 单操作者场景不紧急 |

---

## 16. Risk Assessment

### 高风险

1. **bootstrap/__init__.py 大改** — 这是 432 行的 DI 装配入口, 插件相关代码散布在多处. 需要仔细替换, 不能遗漏引用.
2. **config_control_plane.py 的 `reload_runtime_configuration()`** — 这是全局热刷新入口, 需要正确处理插件重载 (调 reconcile_all 而非旧的 reload_from_config).

### 中风险

3. **Model target revalidate/rollback** — 逻辑复杂, 需要完整移植到 Host 并保留异常安全性.
4. **__init__.py facade re-export** — 228-498 行的导出列表, 需要把旧符号全部替换为新符号, 外部依赖可能通过 facade 导入.

### 低风险

5. **WebUI 重写** — 独立前端组件, 不影响后端逻辑.
6. **测试适配** — 测试数量可控 (约 10 个用例), 且有清晰的 fake 对象模式.
