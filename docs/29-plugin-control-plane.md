# 插件管控：四对象模型

## 当前的问题

插件相关的信息散落在四个地方，每个地方管一件不同的事，但它们没有被正式区分：

1. **磁盘上装了什么插件代码** — `extensions/plugins/` 下的目录，以及 `src/acabot/runtime/plugins/` 里的内建插件。但目前 `extensions/plugins/` 下面全是空目录（只有 `__pycache__`），从未真正工作过。

2. **操作者想启用哪些、怎么配** — `config.yaml` 里的 `runtime.plugins` 列表决定加载谁，`plugins.<name>` 决定每个插件吃什么配置。这两块分开写，没有统一的"一个插件的完整意图"表达。

3. **当前进程里实际跑着什么** — `RuntimePluginManager.loaded` 列表，加上 `failed_plugin_import_paths`。但这些只是内存状态，WebUI 看不到，也没有持久化。

4. **谁来决定加载/卸载/重载** — 这个逻辑现在散落在三个地方：`RuntimePluginManager.reload_from_config()`、`ConfigControlPlane.replace_plugin_configs()`、`RuntimeControlPlane.reload_plugins()`。每个都在做"收敛"，但谁都不是正式的收敛入口。

这四类信息混在一起，直接后果是：

- WebUI 里看到的是 import path（比如 `acabot.runtime.plugins.ops_control:OpsControlPlugin`），而不是一个稳定的插件名。class 一重构，UI 上的标识就断了。

- "没启用"和"启用了但加载失败"分不清，因为没有独立的状态记录。`RuntimePluginManager` 只有一个 `failed_plugin_import_paths` 列表，连插件注册了哪些 tool 都没有快照。

- 内建插件（`BackendBridgeToolPlugin`）和配置插件（`OpsControlPlugin` 等）走完全不同的加载路径。`build_builtin_runtime_plugins()` 硬编码返回实例列表，配置插件走 `load_runtime_plugins_from_config_with_failures()` 动态导入。WebUI 要展示统一的插件列表，就必须把两条路径的结果拼起来。

- `extensions/plugins/` 的目录插件机制从未真正实现。设计上想让用户往这个目录里扔代码就能发现新插件，但现在没有扫描逻辑，也没有 manifest 协议。

这些问题不是靠打补丁能修的。根本原因是：关于插件的四个不同问题（有什么、想怎样、现在怎样、怎么变成那样）没有被拆成独立的对象。


## 解决方案：四个对象各管一件事

### PluginPackage — 系统里有什么插件可以用

每个插件，不管是内建的还是外部扩展的，都应该有一份正式的包描述。

对于扩展插件，包描述写在 `extensions/plugins/<plugin_id>/plugin.yaml`：

```yaml
plugin:
  plugin_id: notebook
  display_name: Notebook
  source_kind: extensions        # 或 builtin
  entrypoint: plugins.notebook:NotebookPlugin
  version: "1"
  default_config:
    max_notes: 100
  config_schema: config.schema.json   # 可选
```

对于内建插件，不需要额外的 yaml 文件。直接在 `RuntimePlugin` 子类上声明类属性：

```python
class BackendBridgeToolPlugin(RuntimePlugin):
    plugin_id = "backend_bridge_tool"
    display_name = "Backend Bridge"
    source_kind = "builtin"
```

不管来源如何，最终都被读成同一个 `PluginPackage` 数据对象。WebUI 看到的是统一的插件列表，区别只在 `source_kind` 字段。

PluginPackage 只回答"这个插件是什么"。它不管操作者想不想启用，也不管当前是否加载成功。


### PluginSpec — 操作者想让这个插件怎么跑

操作者的意图单独存一份，放在 `runtime_config/plugins/<plugin_id>/plugin.yaml`：

```yaml
plugin:
  plugin_id: notebook
  enabled: true
config:
  max_notes: 200
```

这个文件只回答两件事：要不要启用、配置是什么。

它取代了现在 `config.yaml` 里分散在两处的写法（`runtime.plugins` 列表 + `plugins.<name>` 配置块）。改完之后，每个插件的完整意图集中在一个文件里。

如果某个插件的 Spec 文件不存在，就视为"操作者没有表态"，等同于 disabled。不自动创建 Spec 文件，让操作者显式启用。


### PluginStatus — 运行时观察到的事实

每次加载/卸载/失败后，runtime 把实际结果写到 `runtime_data/plugins/<plugin_id>/status.json`：

```json
{
  "plugin_id": "notebook",
  "phase": "loaded",
  "load_error": "",
  "registered_tools": ["take_note"],
  "registered_hooks": ["on_event:NoteHook"],
  "updated_at": "2026-04-01T12:00:00Z"
}
```

`phase` 的可能值：

| phase | 含义 |
|-------|------|
| `disabled` | Spec 里 enabled=false，或者 Spec 不存在 |
| `loaded` | 加载成功，正在运行 |
| `failed` | 尝试加载了，但 setup() 抛异常 |
| `uninstalled` | Spec 还在，但包已经从磁盘删除了 |

这四种状态在运维上完全不同，现在的实现只有"在 loaded 列表里"和"在 failed 列表里"两种，根本不够用。

PluginStatus 只记录事实。它不管操作者想怎样，也不管包本身长什么样。


### PluginReconciler — 把意图变成现实

Reconciler 是唯一负责"决定该 load 还是 unload"的地方。它读前面三个对象，计算差异，执行动作，写回 Status。

具体逻辑：

```
对每个已知的 plugin_id：
  拿到它的 Package（如果有）
  拿到它的 Spec（如果有）
  拿到它当前的 Status 和内存中的加载状态

  然后判断：
  - Package 存在 + Spec enabled + 当前没加载  →  load
  - Package 存在 + Spec disabled + 当前已加载  →  unload
  - Package 或 Spec 的内容变了 + 当前已加载  →  reload
  - Spec 存在但 Package 不见了                →  标记 uninstalled

  执行完动作后，写回新的 Status
```

现在的代码里，这套逻辑散落在：
- `RuntimePluginManager.reload_from_config()` — 负责实际的 unload + load
- `ConfigControlPlane.replace_plugin_configs()` — 负责写 config + 触发重载
- `RuntimeControlPlane.reload_plugins()` — 负责中转调用

引入 Reconciler 之后，这三个地方都不再直接操作加载/卸载。API 只改 Spec，RuntimeApp 启动时和 Spec 变更后调用 Reconciler，Reconciler 调用 RuntimePluginManager 的底层 load/unload 能力。

**触发时机**只有两个：
1. RuntimeApp 启动时，全量 reconcile 一次
2. Spec 被修改后（WebUI 保存、运维命令），对变更的插件 reconcile

不做定时轮询，不做文件 watch。


## 插件的正式身份是 plugin_id，不是 import path

现在 `config_control_plane.py` 里的 `_plugin_name_from_path()` 从 import path 里提取 Symbol 名当标识：

```python
# 现在的做法
"acabot.runtime.plugins.ops_control:OpsControlPlugin"  →  "OpsControlPlugin"
```

class 改名就断了。操作者也不应该看到 Python 模块路径。

改造后，所有地方统一用 `plugin_id`：

```
ops_control
notebook
backend_bridge_tool
napcat_tools
reference_tools
```

WebUI、磁盘文件、Status、日志、API 全部围绕这一个 ID。import path 降为 Package 内部的实现细节。


## 磁盘布局总览

和项目已有的三层目录完全对齐：

```
extensions/plugins/notebook/          ← PluginPackage（扩展插件的包描述 + 代码）
  plugin.yaml
  __init__.py

runtime_config/plugins/notebook/      ← PluginSpec（操作者意图）
  plugin.yaml

runtime_data/plugins/notebook/        ← PluginStatus（运行时事实）
  status.json
```

内建插件不占 `extensions/` 的位置，它们的 Package 信息从类属性读取。但它们同样有自己的 Spec 和 Status 文件。


## API

```
GET  /api/system/plugins                         列表，返回每个插件的 Package + Spec + Status 合并视图
GET  /api/system/plugins/<plugin_id>              单个插件的完整视图
PUT  /api/system/plugins/<plugin_id>/spec         修改 Spec（enabled / config），保存后自动触发 reconcile
GET  /api/system/plugins/<plugin_id>/status       查看运行状态和错误信息
```

WebUI 的主要操作是"改 Spec"。点下保存按钮 → 写 Spec 文件 → 触发 Reconciler → 返回新的 Status。UI 不直接调用 load / unload。


## 对 WebUI 的收益

有了这四个对象，插件管理页可以清楚地展示三层信息：

- **来源**：内建还是扩展安装的（来自 Package）
- **意图**：操作者是否启用了、配了什么参数（来自 Spec）
- **事实**：是否加载成功、注册了哪些 tool、失败原因是什么（来自 Status）

而不是现在这样，只能看到一个 import path 列表加一个 enabled 开关。


## 和现有代码的关系

### 可以直接复用

- `RuntimePlugin` 基类的生命周期协议（setup / teardown / hooks / tools / model_slots）不用改
- `RuntimeHookRegistry` 的 hook 管理完全不用动
- `RuntimePluginManager` 的 `load_plugin()` 和 `unload_plugins()` 底层能力继续用
- `ToolBroker` 的按来源注册/注销机制继续用

### 需要重构

- **`RuntimePluginManager`**：现在 972 行，身兼 hook 管理、插件加载、配置解析、model target 注册。引入 Reconciler 后，把生命周期决策抽出去，Manager 只保留"管理已加载插件的运行时交互"职责。

- **`ConfigControlPlane` 的插件部分**：`list_plugin_configs()` 和 `replace_plugin_configs()` 这两个方法，以及 `_plugin_name_from_path()` / `_plugin_display_name_from_path()` 这些 hack，全部删掉，换成 Reconciler + Spec 读写。

- **`build_builtin_runtime_plugins()`**：不再硬编码返回实例列表，改为从 builtin 插件类的类属性生成 Package catalog。

### 可以删掉

- `config.yaml` 里的 `runtime.plugins` 列表和 `plugins.<name>` 配置块，被 `runtime_config/plugins/` 取代
- `ConfigControlPlane` 里所有 `_probe_plugin_import_error()` / `_plugin_name_from_path()` 之类从 import path 推导信息的逻辑


## 实施步骤

不需要兼容迁移，项目没有外部用户。两步完成：

**第一步：建模型**

引入 PluginPackage / PluginSpec / PluginStatus 三个数据对象。实现 PluginReconciler，把现有三处散落的收敛逻辑统一收进来。内建插件在类上加 `plugin_id` / `display_name` / `source_kind` 类属性。扩展插件在 `extensions/plugins/<id>/plugin.yaml` 声明 manifest。Spec 写到 `runtime_config/plugins/<id>/plugin.yaml`，Status 写到 `runtime_data/plugins/<id>/status.json`。

**第二步：切 API 和 WebUI**

删掉 `ConfigControlPlane` 的插件相关方法，删掉 `config.yaml` 里的旧格式。HTTP API 换成上面的资源接口。WebUI 插件管理页面按 Package / Spec / Status 三层展示。
