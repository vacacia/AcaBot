# 插件管控重构

## 当前的问题

插件相关的信息散落在四个地方，每个地方管一件不同的事，但它们没有被正式区分：

1. **磁盘上装了什么插件代码** — `extensions/plugins/` 下的目录，以及 `src/acabot/runtime/plugins/` 里的内建插件。但目前 `extensions/plugins/` 下面全是空目录（只有 `__pycache__`），从未真正工作过。

2. **操作者想启用哪些、怎么配** — `config.yaml` 里的 `runtime.plugins` 列表决定加载谁，`plugins.<name>` 决定每个插件吃什么配置。这两块分开写，没有统一的"一个插件的完整意图"表达。

3. **当前进程里实际跑着什么** — `RuntimePluginManager.loaded` 列表，加上 `failed_plugin_import_paths`。但这些只是内存状态，WebUI 看不到，也没有持久化。

4. **谁来决定加载/卸载/重载** — 这个逻辑散落在三个地方：`RuntimePluginManager.reload_from_config()`、`ConfigControlPlane.replace_plugin_configs()`、`RuntimeControlPlane.reload_plugins()`。每个都在做"收敛"，但谁都不是正式的收敛入口。

直接后果：

- WebUI 里看到的是 import path（比如 `acabot.runtime.plugins.ops_control:OpsControlPlugin`），class 一重构就断。

- "没启用"和"启用了但加载失败"分不清。`RuntimePluginManager` 只有一个 `failed_plugin_import_paths` 列表，连插件注册了哪些 tool 都没有快照。

- 内建插件和配置插件走完全不同的加载路径。`build_builtin_runtime_plugins()` 硬编码返回实例列表，配置插件走 `load_runtime_plugins_from_config_with_failures()` 动态导入。

- `extensions/plugins/` 的目录插件机制从未真正实现。没有扫描逻辑，也没有 manifest 协议。

- `RuntimePluginManager`（972 行）身兼 hook 管理、插件加载、配置解析、model target 注册，职责过多。


## 解决方案概览

用六个模块取代现有的 `plugin_manager.py`：

```
src/acabot/runtime/
  plugin_protocol.py      ← 插件作者对接的接口定义
  plugin_package.py       ← PluginPackage 数据对象 + PackageCatalog
  plugin_spec.py          ← PluginSpec 数据对象 + SpecStore
  plugin_status.py        ← PluginStatus 数据对象 + StatusStore
  plugin_reconciler.py    ← PluginReconciler（决策层）
  plugin_runtime_host.py  ← PluginRuntimeHost（执行层）
```

磁盘上对应三层目录：

```
extensions/plugins/<id>/          ← PluginPackage（manifest + 代码）
  plugin.yaml
  __init__.py

runtime_config/plugins/<id>/      ← PluginSpec（操作者意图）
  plugin.yaml

runtime_data/plugins/<id>/        ← PluginStatus（观察结果）
  status.json
```

核心分工：

- **PluginReconciler** 是决策层——读 Package + Spec + Host 当前状态，计算差异，调 Host 执行，写 Status。
- **PluginRuntimeHost** 是执行层——持有已加载的插件实例，执行 load/unload/teardown，管理 hook 和 tool 注册，提供 `run_hooks()` 给 pipeline 调用。

Reconciler 是大脑，Host 是手脚。


## plugin_protocol.py — 插件接口定义

从现有 `plugin_manager.py` 中提取，不改动接口本身。这一层是插件作者写代码时对接的契约，所有其他模块都依赖它，它不依赖插件控制面模块（package/spec/status/reconciler/host）。

包含：

- `RuntimePlugin`（ABC）— 插件基类，声明 `setup()` / `teardown()` / `hooks()` / `tools()` / `runtime_tools()` / `model_slots()`
- `RuntimePluginContext` — 插件 setup 时可见的最小运行时上下文
- `RuntimeHookPoint` / `RuntimeHook` / `RuntimeHookResult` — hook 体系
- `RuntimeToolRegistration` — runtime-native 工具定义
- `RuntimePluginModelSlot` — 插件声明的模型槽位

`RuntimePluginContext` 的变化：

```python
@dataclass
class RuntimePluginContext:
    """插件 setup 时可见的最小 runtime 上下文"""
    plugin_config: dict[str, Any]       # 合并后的最终配置（default_config | spec.config）
    plugin_id: str                      # 当前插件的 ID
    data_dir: Path                      # 插件专属可写目录：runtime_data/plugins/<id>/data/
    gateway: GatewayProtocol
    tool_broker: ToolBroker
    reference_backend: ReferenceBackend | None = None
    sticky_notes: StickyNoteService | None = None
    computer_runtime: ComputerRuntime | None = None
    skill_catalog: SkillCatalog | None = None
    control_plane: RuntimeControlPlane | None = None
```

原来的 `config` 字段（整个全局 Config 对象）改成 `plugin_config`（这个插件的最终配置 dict）。插件不再拿到全局配置，只能看到自己那份。`get_plugin_config()` 方法删掉。

### 新增能力：插件数据目录

`context.data_dir` 指向 `runtime_data/plugins/<plugin_id>/data/`，Host 在 load_plugin 时自动创建。插件可以在这个目录下自由读写文件（缓存、数据库、生成的报告等）。

### 依赖其他基础设施的能力（本轮不实现）

以下能力是插件体系需要的，但依赖尚未完成的 runtime 基础设施。本轮只在设计里记录方向，不进 `RuntimePluginContext` 的字段。等各自基础设施就绪后，再往 context 里加对应的注入。

**LLM 调用** — 插件通过 `model_slots()` 声明模型槽位（这部分协议已存在），runtime 注册为 `plugin:<plugin_id>:<slot_id>` 的 ModelTarget，操作者在 WebUI 绑定模型。插件运行时需要一个统一的 model service 来执行调用，不直接碰 litellm。当前 runtime 还没有这个统一 service，等它就绪后注入 context。

**定时任务** — 插件需要注册定时/周期性任务的能力，框架在 unload/teardown 时自动取消。AcaBot 后续会有自己的定时任务基础设施，届时接入。

**富消息发送** — 当前 Gateway 面向 LLM agent 的文本回复设计，不支持构造包含图片、视频、转发节点等 IM 原生消息组件的消息。需要链接解析、媒体转发等场景的插件在现有 Gateway 下无法实现这类功能。这是 Gateway 层的演进方向，不是插件协议层该解决的。

**平台适配器 API** — 获取群列表、成员信息、用户头像、上传群文件等操作，当前 GatewayProtocol 不提供。需要群分析等场景的插件依赖这些能力。同样是 Gateway 层的演进方向。


## plugin_package.py — PluginPackage 和 PackageCatalog

### PluginPackage

```python
@dataclass(frozen=True)
class PluginPackage:
    plugin_id: str                                    # 稳定身份，如 "ops_control"
    display_name: str                                 # WebUI 展示名
    package_root: Path                                # extensions/plugins/ops_control/
    entrypoint: str                                   # "plugins.ops_control:OpsControlPlugin"
    version: str = "1"
    default_config: dict[str, Any] = field(default_factory=dict)
    config_schema: dict[str, Any] | None = None       # JSON Schema，WebUI 用它生成表单
```

`package_root` 由 PackageCatalog 扫描时填入，Host 用它定位插件代码目录，不需要从约定反推。

### 磁盘格式

`extensions/plugins/<plugin_id>/plugin.yaml`：

```yaml
plugin:
  plugin_id: ops_control
  display_name: Ops Control
  # entrypoint 可选，不写则默认 plugins.<plugin_id>:Plugin
  version: "1"
  default_config:
    prefix: "/"
  config_schema:
    type: object
    properties:
      prefix:
        type: string
        description: "命令前缀"
      allowed_actor_ids:
        type: array
        items:
          type: string
        description: "允许使用运维命令的用户"
```

`entrypoint` 可以不写。PackageCatalog 扫描时按 `plugins.<plugin_id>:Plugin` 补全。只有当类名不是 `Plugin` 或模块结构特殊时才需要显式声明。

`config_schema` 直接内联在 plugin.yaml 里，JSON Schema 格式。没有可配置项的简单插件可以省略这个字段。

`plugin_id` 必须和目录名一致。不一致的 → 报错跳过。

### 导入路径约定

`extensions/plugins/` 是 Python 3.3+ 隐式命名空间包（不需要 `__init__.py`），所有插件在 `plugins.` 命名空间下，不污染顶层 import 空间。

`plugins.ops_control:OpsControlPlugin` 表示 `from plugins.ops_control import OpsControlPlugin`。

前提：`extensions/` 必须在 sys.path 上。三种运行方式各自保证：

- **Docker**：Dockerfile 里 `PYTHONPATH=/app/src:/app/extensions`
- **本地直接启动**：runtime bootstrap 时主动把 `extensions/` 加进 `sys.path`（基于项目根目录，和 `docs/28-directory-restructure.md` 中 extensions 路径解析一致，不基于 `config.base_dir()`）
- **测试**：`tests/conftest.py` 把 `extensions/` 加进 `sys.path`

### PackageCatalog

```python
class PackageCatalog:
    """扫描 extensions/plugins/ 下所有 plugin.yaml，构建 PluginPackage 集合"""

    def __init__(self, extensions_plugins_dir: Path): ...
    def scan(self) -> tuple[dict[str, PluginPackage], list[PackageScanError]]: ...
    def get(self, plugin_id: str) -> PluginPackage | None: ...  # 读最新缓存
```

`scan()` 遍历 `extensions/plugins/` 下每个子目录，找 `plugin.yaml`，解析成 `PluginPackage`。没有 `plugin.yaml` 的子目录跳过。

解析失败的不会被静默丢弃——`scan()` 同时返回解析错误列表：

```python
@dataclass(frozen=True)
class PackageScanError:
    plugin_id: str      # 从目录名推断
    error: str

def scan(self) -> tuple[dict[str, PluginPackage], list[PackageScanError]]: ...
```

Reconciler 拿到解析错误后，为对应的 plugin_id 生成 `PluginStatus(phase="failed", load_error="...")`，这样 WebUI 能看到"这个插件的 manifest 写坏了"，不会错误地显示为 uninstalled 或从列表消失。


## plugin_spec.py — PluginSpec 和 SpecStore

### PluginSpec

```python
@dataclass(frozen=True)
class PluginSpec:
    """操作者意图。enabled 控制是否启用，config 只存覆盖项。
    缺失的配置值由 PluginPackage.default_config 提供。"""
    plugin_id: str
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)
```

三种状态的区别：

- **Spec 文件不存在** = 操作者从未配置过，等同 disabled
- **enabled: false** = 操作者明确禁用，但保留配置。下次启用时配置还在
- **delete** = 删掉 Spec 文件，回到"从未配置"，配置也清空

配置覆盖语义：`effective_config = package.default_config | spec.config`，顶层 key replace，不做深合并。

### 磁盘格式

`runtime_config/plugins/<plugin_id>/plugin.yaml`：

```yaml
plugin:
  plugin_id: ops_control
  enabled: true
config:
  prefix: "/"
  allowed_actor_ids:
    - "qq:user:123456"
```

### SpecStore

```python
class SpecStore:
    """读写 runtime_config/plugins/ 下的 PluginSpec"""

    def __init__(self, plugins_config_dir: Path): ...

    def load_all(self) -> tuple[dict[str, PluginSpec], list[SpecParseError]]: ...
    def load(self, plugin_id: str) -> PluginSpec | None: ...
    def save(self, spec: PluginSpec) -> None: ...       # 原子写（临时文件 + rename）
    def delete(self, plugin_id: str) -> None: ...       # 删文件+目录
```

解析失败的同样不会被静默丢弃——`load_all()` 同时返回解析错误列表：

```python
@dataclass(frozen=True)
class SpecParseError:
    plugin_id: str
    error: str

def load_all(self) -> tuple[dict[str, PluginSpec], list[SpecParseError]]: ...
```

Reconciler 拿到解析错误后，为对应的 plugin_id 生成 `PluginStatus(phase="failed", load_error="...")`，WebUI 能看到"这个插件的配置文件写坏了"，不会错误地显示为 disabled。

`save()` / `delete()` 用原子写，和现有代码（`config_control_plane.py` line 1252、`model_registry.py` line 1446）保持一致。

`save()` 写完文件后不触发任何副作用。调用方（API handler）负责触发 Reconciler。


## plugin_status.py — PluginStatus 和 StatusStore

### PluginStatus

```python
PluginPhase = Literal["disabled", "loaded", "failed", "uninstalled"]

@dataclass
class PluginStatus:
    """Reconciler 的输出，持久化的观察结果。不参与决策。"""
    plugin_id: str
    phase: PluginPhase
    load_error: str = ""
    registered_tools: list[str] = field(default_factory=list)
    registered_hooks: list[str] = field(default_factory=list)   # 如 "pre_agent:OpsCommandHook"
    updated_at: str = ""                                        # ISO 8601
```

`registered_tools` 和 `registered_hooks` 来自 Host 的 `PluginLoadSnapshot`（见下文），不是 Reconciler 自己推断的。

phase 含义：

| phase | 含义 |
|-------|------|
| `disabled` | Spec 里 enabled=false，或 Spec 不存在 |
| `loaded` | 加载成功，正在运行 |
| `failed` | 尝试加载或卸载时抛异常 |
| `uninstalled` | Spec 还在，但包已经从磁盘删除了 |

unload 失败时 phase 也是 `failed`，因为插件实际上可能还驻留在内存里没被正确清理。

### StatusStore

```python
class StatusStore:
    """读写 runtime_data/plugins/ 下的 PluginStatus"""

    def __init__(self, plugins_data_dir: Path): ...

    def load_all(self) -> dict[str, PluginStatus]: ...
    def load(self, plugin_id: str) -> PluginStatus | None: ...
    def save(self, status: PluginStatus) -> None: ...    # 原子写
    def delete(self, plugin_id: str) -> None: ...
```

Reconciler 是唯一写入方。API 和 WebUI 只读。

进程重启后 status.json 不参与决策——Reconciler 启动时从 Package + Spec + Host 内存状态重新算，算完覆盖写入。status.json 缺失不是错误，只是说明还没被 reconcile 过。

单个坏文件 warning log，跳过继续。


## plugin_runtime_host.py — PluginRuntimeHost

从现有 `RuntimePluginManager` 瘦身而来。只保留运行时执行能力，不做任何决策。

### PluginLoadSnapshot

```python
@dataclass(frozen=True)
class PluginLoadSnapshot:
    """Host 加载一个插件后返回的摘要，Reconciler 用它填 Status"""
    tool_names: list[str]
    hook_descriptors: list[str]      # 如 "pre_agent:OpsCommandHook"
```

### PluginRuntimeHost

```python
class PluginRuntimeHost:
    """持有已加载的插件实例，执行 load/unload/teardown，管理 hook 和 tool 注册"""

    def __init__(
        self,
        tool_broker: ToolBroker,
        model_target_catalog: MutableModelTargetCatalog | None = None,
    ): ...

    async def load_plugin(
        self,
        package: PluginPackage,
        context: RuntimePluginContext,
    ) -> PluginLoadSnapshot: ...

    async def unload_plugin(self, plugin_id: str) -> None: ...
    async def teardown_all(self) -> None: ...
    def loaded_plugin_ids(self) -> set[str]: ...

    async def run_hooks(
        self,
        point: RuntimeHookPoint,
        ctx: RunContext,
    ) -> RuntimeHookResult: ...
```

`load_plugin()` 的完整流程：按 `package.entrypoint` 导入并实例化 RuntimePlugin → 调 `setup(context)` → 注册 hook/tool/model target → 返回 PluginLoadSnapshot。

`unload_plugin()` 的完整流程：从 ToolBroker 注销该插件的所有工具（按 `source=f"plugin:{plugin_id}"` 过滤）→ 注销 model target → 调 `teardown()` → 重建 hook registry → 从已加载集合移除。

`run_hooks()` 的行为和现有 Manager 一样：按 priority 排序执行，单个 hook 异常不影响其他（记日志继续），skip_agent 短路返回。

`loaded_plugin_ids()` 返回已加载插件 ID 的拷贝集合。

内部结构：

- `_loaded: dict[str, RuntimePlugin]` — plugin_id → 实例
- `_hook_registry: RuntimeHookRegistry` — 内部实现细节，不暴露
- `_plugin_hooks: dict[str, list[...]]` — 每个插件注册了哪些 hook，卸载时精确清理
- `_plugin_tool_sources: dict[str, str]` — 每个插件在 ToolBroker 里的 source 标识

RuntimeHookRegistry 作为 Host 的内部实现，不独立成公开模块。pipeline 通过 `host.run_hooks()` 调用，不直接接触 registry。


## plugin_reconciler.py — PluginReconciler

### 接口

```python
class PluginReconciler:
    def __init__(
        self,
        catalog: PackageCatalog,
        spec_store: SpecStore,
        status_store: StatusStore,
        host: PluginRuntimeHost,
        context_factory: Callable[[str, dict[str, Any]], RuntimePluginContext],
    ): ...

    async def reconcile_all(self) -> list[PluginStatus]: ...
    async def reconcile_one(self, plugin_id: str) -> PluginStatus: ...
```

`context_factory` 是 bootstrap 时注入的工厂闭包，接收合并后的 plugin_config，返回 RuntimePluginContext。Reconciler 不直接持有 gateway、tool_broker 等运行时依赖。

### reconcile_all

```python
async def reconcile_all(self) -> list[PluginStatus]:
    packages, package_errors = self.catalog.scan()
    specs, spec_errors = self.spec_store.load_all()

    # 解析失败的直接生成 failed 状态并落盘
    results = []
    error_ids: set[str] = set()
    for err in package_errors:
        error_ids.add(err.plugin_id)
        status = PluginStatus(plugin_id=err.plugin_id, phase="failed", load_error=f"bad manifest: {err.error}", ...)
        self.status_store.save(status)
        results.append(status)
    for err in spec_errors:
        if err.plugin_id not in error_ids:
            error_ids.add(err.plugin_id)
            status = PluginStatus(plugin_id=err.plugin_id, phase="failed", load_error=f"bad spec: {err.error}", ...)
            self.status_store.save(status)
            results.append(status)

    all_ids = (set(packages) | set(specs) | self.host.loaded_plugin_ids()) - error_ids

    for plugin_id in sorted(all_ids):
        status = await self._reconcile(
            plugin_id,
            package=packages.get(plugin_id),
            spec=specs.get(plugin_id),
        )
        results.append(status)
    return results
```

### _reconcile（内部方法）

```python
async def _reconcile(self, plugin_id, package, spec) -> PluginStatus:
    is_loaded = plugin_id in self.host.loaded_plugin_ids()

    # Spec 存在但 Package 不见了
    if spec and not package:
        if is_loaded:
            await self.host.unload_plugin(plugin_id)
        status = PluginStatus(plugin_id=plugin_id, phase="uninstalled", ...)

    # 没有 Spec 或 Spec disabled
    elif not spec or not spec.enabled:
        if is_loaded:
            await self.host.unload_plugin(plugin_id)
        status = PluginStatus(plugin_id=plugin_id, phase="disabled", ...)

    # Package 存在 + Spec enabled
    elif package and spec.enabled:
        if is_loaded:
            # 已加载，先 unload 再 load（等于 reload）
            try:
                await self.host.unload_plugin(plugin_id)
            except Exception as e:
                status = PluginStatus(plugin_id=plugin_id, phase="failed", load_error=str(e), ...)
                self.status_store.save(status)
                return status

        merged_config = package.default_config | spec.config
        context = self.context_factory(plugin_id, merged_config)
        try:
            snapshot = await self.host.load_plugin(package, context)
            status = PluginStatus(
                plugin_id=plugin_id,
                phase="loaded",
                registered_tools=snapshot.tool_names,
                registered_hooks=snapshot.hook_descriptors,
                ...
            )
        except Exception as e:
            status = PluginStatus(plugin_id=plugin_id, phase="failed", load_error=str(e), ...)

    self.status_store.save(status)
    return status
```

`reconcile_one()` 对外用于单插件触发，内部现取 package 和 spec 再调 `_reconcile()`。

### 触发时机

1. **app.start()** — 调 `reconcile_all()`
2. **Spec 变更后** — API handler 调 `reconcile_one(plugin_id)`
3. **手动 rescan** — WebUI "重新扫描"按钮调 `reconcile_all()`

不做定时轮询，不做文件 watch。运行期间的插件变更入口只有 Spec 保存和手动 rescan。`extensions/plugins/` 下的新增、删除、改代码，不自动感知；要么重启后 `reconcile_all()`，要么通过 WebUI 手动触发 `reconcile_all()`。


## 插件的正式身份是 plugin_id，不是 import path

现在 `config_control_plane.py` 里的 `_plugin_name_from_path()` 从 import path 里提取 Symbol 名当标识。class 改名就断。

改造后，所有地方统一用 `plugin_id`。WebUI、磁盘文件、Status、日志、API 全部围绕这一个 ID。import path 降为 Package 内部的实现细节（`entrypoint` 字段）。


## API

删掉现有的 4 个插件端点，换成资源接口。

### 删除

```
GET  /api/plugins                      → 删
POST /api/plugins/reload               → 删
GET  /api/system/plugins/config        → 删
PUT  /api/system/plugins/config        → 删
```

### 新增

**GET /api/system/plugins** — 所有插件的合并视图

```json
{
  "plugins": [
    {
      "plugin_id": "ops_control",
      "package": {
        "display_name": "Ops Control",
        "version": "1",
        "entrypoint": "plugins.ops_control:OpsControlPlugin",
        "default_config": {"prefix": "/"},
        "config_schema": { "..." : "..." }
      },
      "spec": {
        "enabled": true,
        "config": {"prefix": "/", "allowed_actor_ids": ["qq:user:123456"]}
      },
      "status": {
        "phase": "loaded",
        "load_error": "",
        "registered_tools": [],
        "registered_hooks": ["pre_agent:OpsCommandHook"],
        "updated_at": "2026-04-02T15:00:00Z"
      },
      "effective_config": {"prefix": "/", "allowed_actor_ids": ["qq:user:123456"]}
    }
  ]
}
```

`package` / `spec` / `status` 各自可以为 null。`effective_config` 是 `default_config | spec.config` 的合并结果，方便前端直接用。

**GET /api/system/plugins/\<plugin_id\>** — 单个插件的完整视图，格式同上数组里的单项。

**PUT /api/system/plugins/\<plugin_id\>/spec** — 修改 Spec

请求体：

```json
{
  "enabled": true,
  "config": {"prefix": "/", "allowed_actor_ids": ["qq:user:123456"]}
}
```

保存 Spec 后自动触发 `reconciler.reconcile_one(plugin_id)`，返回更新后的完整插件视图。

**DELETE /api/system/plugins/\<plugin_id\>/spec** — 删除 Spec

删 Spec 文件，回到"从未配置"状态（配置清空 + 插件禁用）。触发 reconcile，返回更新后的视图。

**POST /api/system/plugins/reconcile** — 手动全量 reconcile

用于 `extensions/plugins/` 下有代码变更后手动刷新。返回和 GET 同形状的完整视图 `{"plugins": [...]}`，因为 rescan 后 Package 本身也可能变了。

### API 业务逻辑归属

遵循现有分层约定（`08-webui-and-control-plane.md`）：业务逻辑放 control plane，`http_api.py` 只做 HTTP 适配。

给 `RuntimeControlPlane` 增加一组插件资源方法：

```python
# control_plane.py 新增
def list_plugins(self) -> list[PluginView]: ...
def get_plugin(self, plugin_id: str) -> PluginView | None: ...
async def update_plugin_spec(self, plugin_id: str, enabled: bool, config: dict) -> PluginView: ...
async def delete_plugin_spec(self, plugin_id: str) -> PluginView: ...
async def reconcile_all_plugins(self) -> list[PluginView]: ...
```

这些方法内部调 `reconciler` / `spec_store` / `catalog` / `status_store`。`http_api.py` 只做请求解析 + 调 control plane + 返回 JSON。

### /api/status 里的 loaded_plugins

`control_plane.py` 的 `_list_loaded_plugins()` 保留，数据源从 `plugin_manager.loaded` 换成 `host.loaded_plugin_ids()`。`/api/status` 里的 `loaded_plugins` 以后只含通过新插件体系加载的 extension plugins。本轮初始为空列表。BackendBridgeTool 不在其中。


## WebUI 插件管理页

### 页面结构

一个 PluginsView.vue，列表 + 展开面板，不做详情页跳转。

**列表项**：每个插件一行，显示 display_name（package 为 null 时 fallback 到 plugin_id）、phase 徽章（loaded / disabled / failed / uninstalled）、enabled 开关（绑 `spec?.enabled ?? false`）。

**展开面板**（点击列表项展开）：
- 来源信息：版本号
- 状态信息：registered_tools、registered_hooks、load_error（如果 failed）
- 配置编辑：schema 驱动的表单

### schema 驱动表单

如果 `package.config_schema` 存在，根据 JSON Schema 自动生成表单字段：
- `string` → 文本输入
- `number` → 数字输入
- `boolean` → 开关
- `array` of `string` → 可编辑的标签列表
- `object` → JSON 编辑器整块编辑（因为配置覆盖语义是顶层 key replace，不做深合并，嵌套表单会误导用户）

表单编辑的是 `spec.config`（override 部分）。每个字段的 placeholder 来自 `package.default_config`，用户清空则删掉这个 key（回退到默认值）。

如果 `package.config_schema` 不存在，显示 `effective_config` 的只读 JSON 视图，不提供编辑。

### 操作按钮

- **enabled 开关** — `PUT /api/system/plugins/<id>/spec`
- **保存配置** — `PUT /api/system/plugins/<id>/spec`
- **恢复默认配置** — `PUT spec`，`config` 设为 `{}`，`enabled` 保持不变
- **移除并禁用** — `DELETE /api/system/plugins/<id>/spec`，带确认对话框
- **页面顶部"重新扫描"** — `POST /api/system/plugins/reconcile`

### 交互流程

1. 页面加载 → `GET /api/system/plugins` 拿完整列表
2. 切换 enabled 开关 → `PUT spec`，用返回值更新本地状态
3. 编辑配置保存 → `PUT spec`，同上
4. 恢复默认配置 → `PUT spec` + 空 config
5. 移除并禁用 → `DELETE spec`
6. 重新扫描 → `POST reconcile`，用返回值替换整个列表


## 旧插件处理

### 删除的插件

`OpsControlPlugin`、`NapCatToolsPlugin`、`ReferenceToolsPlugin` — 这三个旧插件不迁移，直接删除代码。以后需要时用新体系重写。

`extensions/plugins/` 下现有的空目录（`napcat_tools/`、`notepad/`）也清掉。本轮落地后 `extensions/plugins/` 存在但为空。

### BackendBridgeToolPlugin

暂时保留 `plugins/backend_bridge_tool.py` 文件。它不走新插件体系——bootstrap 里直接实例化并手动注册 tool 到 ToolBroker。它不经过 Reconciler，不出现在插件列表，不出现在 `/api/status` 的 `loaded_plugins` 里。

文件内的导入从 `plugin_manager` 换到 `plugin_protocol`（否则删了 `plugin_manager.py` 后导入会炸）。文件头标注为过渡期死代码，后续用别的方式重做时删除。

### OpsControl 的运维命令

删了 `OpsControlPlugin` 之后，`/status`、`/reload_plugins` 等聊天里的运维命令也没了。当前阶段通过 WebUI 管理插件。运维命令以后用新体系重写时再加回来。


## Bootstrap 集成

### 启动流程

bootstrap 只构造对象，`app.start()` 才做 reconcile：

```python
# bootstrap/__init__.py
catalog = PackageCatalog(extensions_plugins_dir)
spec_store = SpecStore(runtime_config_plugins_dir)
status_store = StatusStore(runtime_data_plugins_dir)
host = PluginRuntimeHost(tool_broker, model_target_catalog)

context_factory = make_context_factory(gateway, tool_broker, reference_backend, ...)
reconciler = PluginReconciler(catalog, spec_store, status_store, host, context_factory)

# app.py
async def start(self):
    await self.reconciler.reconcile_all()    # 首次全量 reconcile

async def stop(self):
    await self.host.teardown_all()           # 逆序清理所有已加载插件
```

### context_factory

```python
def make_context_factory(gateway, tool_broker, reference_backend, ...):
    def factory(plugin_id: str, plugin_config: dict[str, Any]) -> RuntimePluginContext:
        data_dir = runtime_data_plugins_dir / plugin_id / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return RuntimePluginContext(
            plugin_config=plugin_config,
            plugin_id=plugin_id,
            data_dir=data_dir,
            gateway=gateway,
            tool_broker=tool_broker,
            reference_backend=reference_backend,
            ...
        )
    return factory
```


## 影响面

### 删除

| 文件 | 说明 |
|------|------|
| `plugin_manager.py` | 整个删除。协议搬到 `plugin_protocol.py` |
| `plugins/ops_control.py` | 删除 |
| `plugins/napcat_tools.py` | 删除 |
| `plugins/reference_tools.py` | 删除 |
| `extensions/plugins/napcat_tools/` | 删除空目录 |
| `extensions/plugins/notepad/` | 删除空目录 |
| `snapshots.py` 中 `PluginReloadSnapshot` | 删除 |

### 新增

| 文件 | 内容 |
|------|------|
| `plugin_protocol.py` | RuntimePlugin ABC、RuntimeHook 体系、RuntimePluginContext、RuntimeToolRegistration、RuntimePluginModelSlot |
| `plugin_package.py` | PluginPackage + PackageCatalog |
| `plugin_spec.py` | PluginSpec + SpecStore |
| `plugin_status.py` | PluginStatus + StatusStore |
| `plugin_reconciler.py` | PluginReconciler |
| `plugin_runtime_host.py` | PluginRuntimeHost + PluginLoadSnapshot |

### 修改

| 文件 | 改动 |
|------|------|
| `bootstrap/__init__.py` | 构造 catalog / spec_store / status_store / host / reconciler |
| `bootstrap/components.py` (line 71) | `RuntimeComponents.plugin_manager` → `plugin_reconciler` + `plugin_runtime_host` |
| `bootstrap/builders.py` | 删 `build_builtin_runtime_plugins()`，BackendBridgeTool 改为直接注册 tool |
| `app.py` (line 67, 105, 136, 150, 515) | `plugin_manager` 引用全部替换。`start()` 调 `reconcile_all()`，`stop()` 调 `host.teardown_all()` |
| `pipeline.py` (line 32, 458, 470) | `plugin_manager.run_hooks()` → `host.run_hooks()` |
| `runtime/__init__.py` (line 228-242, 485-493) | 删 plugin_manager + 4 个旧插件类的 re-export，加新模块 export |
| `plugins/__init__.py` | 删 3 个旧插件导出，只保留 BackendBridgeToolPlugin |
| `plugins/backend_bridge_tool.py` | 导入从 `plugin_manager` 换到 `plugin_protocol`，文件头标注过渡期死代码 |
| `control_plane.py` | 删 `reload_plugins()`。`_list_loaded_plugins()` 保留，数据源换成 `host.loaded_plugin_ids()`。新增插件资源方法（list/get/update_spec/delete_spec/reconcile_all） |
| `config_control_plane.py` | 删 `list_plugin_configs()`、`replace_plugin_configs()`、`_probe_plugin_import_error()`、`_plugin_name_from_path()`、`_plugin_display_name_from_path()` |
| `http_api.py` (line 252) | 删 4 个旧插件端点，加 5 个新端点 |
| `PluginsView.vue` | 重写 |
| `api.ts` (line 146) | 删旧插件接口，加新接口 |
| `tests/conftest.py` (line 6) | 删旧 `plugins/` sys.path，换 `extensions/` |
| `tests/` | plugin_manager 相关测试删除或重写，旧 API 端点测试适配，WebUI API 测试适配 |
