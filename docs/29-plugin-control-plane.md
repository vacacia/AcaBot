# Plugin Control Plane 四对象模型

## Context

当前 runtime 对 plugin 的正式边界其实是裂开的：

- `runtime.plugins` 决定“要加载哪些 plugin”
- 顶层 `plugins.<plugin_name>` 决定“plugin 自己吃什么配置”
- `extensions/plugins/` 如果引入目录插件，则又表达“磁盘上装了哪些 plugin 代码”
- `RuntimePluginManager.load_plugin()` / `unload_plugins()` / `reload_from_config()` 直接操纵当前进程里的运行状态

这四类信息都和 plugin 有关，但它们不是同一件事。

一旦 WebUI 要对 plugin 做 enable / disable / reload / config edit，如果还沿用“import path + 若干散落配置键”的模型，就会立刻出现下面这些问题：

- “已安装”和“已启用”混在一起
- “操作者希望怎样”与“当前实际怎样”混在一起
- UI 可以点按钮，但按钮背后没有单一真源
- 目录插件和 config 插件成为两套世界
- 运行时热重载逻辑散落在 API handler 和 manager 方法里，缺少统一收敛面

这不是实现细节问题，而是对象模型还没有收出来。

## 核心判断

plugin control plane 需要四个正式对象：

- `PluginPackage`
- `PluginSpec`
- `PluginStatus`
- `PluginReconciler`

它们分别回答四个不同的问题：

- `PluginPackage`: 系统里“有什么 plugin 可以用”
- `PluginSpec`: 操作者“希望这个 plugin 以什么方式运行”
- `PluginStatus`: runtime “观察到这个 plugin 现在实际处于什么状态”
- `PluginReconciler`: 谁负责把“操作者意图”收敛成“当前运行事实”

这四个问题看起来都和 plugin 有关，但语义完全不同。把它们揉在一个对象里，短期省事，长期一定失真。

## 为什么恰好是四个对象

### 1. `PluginPackage` 不是配置

`PluginPackage` 只回答资源目录问题：

- 稳定 `plugin_id`
- 展示名称
- 来源类型（builtin / extensions）
- 入口点 `entrypoint`
- 可选版本号
- 可选默认配置
- 可选配置 schema

它表达的是“这个 plugin 是什么”，不是“操作者想不想启用它”。

如果没有 `PluginPackage`，WebUI 看到的就只能是一条 import path。那 plugin 仍然不是正式资源，只是实现细节被直接暴露给操作者。

### 2. `PluginSpec` 不是运行状态

`PluginSpec` 只表达 desired state：

- `enabled`
- operator config payload

它回答的是“操作者想让这个 plugin 怎么跑”，而不是“现在是不是已经跑起来了”。

如果没有 `PluginSpec`，enable / disable / config edit 就没有稳定真源，最后会退化成“点按钮直接调运行时接口”，控制面会失去可解释性。

### 3. `PluginStatus` 不是意图

`PluginStatus` 只表达 observed state：

- 当前阶段：`disabled` / `loaded` / `failed` / `uninstalled`
- 最后一次加载错误
- 注册出的 tool / hook / model slot 摘要
- 最近一次 reconcile 时间

它回答的是“系统现在看到的事实”，不是“操作者想怎样”。

如果没有 `PluginStatus`，控制面就分不清下面几种情况：

- 没启用
- 已启用但加载失败
- 已启用且加载成功
- 已经从磁盘卸载，但 spec 还留着

这几种状态在运维上完全不同，不能混成一个布尔值。

### 4. `PluginReconciler` 不是数据对象

`PluginReconciler` 是收敛器。

它的职责不是保存真源，而是：

- 读 `PluginPackage`
- 读 `PluginSpec`
- 看当前 `PluginStatus`
- 计算 desired vs actual 的 diff
- 决定 load / reload / unload / mark_failed
- 写回新的 `PluginStatus`

如果没有 `PluginReconciler`，这些动作就会散落在：

- HTTP API handler
- control plane service
- plugin manager
- 某些“顺手 reload 一下”的旁路逻辑

系统会越来越像一堆过程调用，而不是一个正式 control plane。

## 这四个对象最优雅的地方

它们把四句完全不同的话拆开了：

- 是什么
- 想怎样
- 现在怎样
- 怎么变成那样

很多系统之所以越做越乱，不是因为代码差，而是因为这四句话全塞进了一个“配置对象”。

四对象模型的美感就在于：

- `Package` 不表达状态
- `Spec` 不表达事实
- `Status` 不表达意图
- `Reconciler` 不持有真源

每个对象只说一句真话。

## 正式真源布局

这套模型最适合映射到 AcaBot 现在正在收的三层目录：

- `extensions/`: 能力包目录
- `runtime_config/`: 操作者真源
- `runtime_data/`: 运行时事实

推荐目录：

```text
extensions/
  plugins/
    notebook/
      plugin.yaml
      __init__.py

runtime_config/
  plugins/
    notebook/
      plugin.yaml

runtime_data/
  plugins/
    notebook/
      status.json
```

### `PluginPackage` 真源

`extensions/plugins/<plugin_id>/plugin.yaml`

```yaml
plugin:
  plugin_id: notebook
  display_name: Notebook
  source_kind: extensions
  entrypoint: plugins.notebook:NotebookPlugin
  version: "1"
  config_schema: config.schema.json
  default_config:
    max_notes: 100
```

这个文件回答：

- 包是谁
- 从哪里 import
- 默认长什么样

它不回答：

- 是否启用
- 当前是否加载成功

### `PluginSpec` 真源

`runtime_config/plugins/<plugin_id>/plugin.yaml`

```yaml
plugin:
  plugin_id: notebook
  enabled: true
config:
  max_notes: 100
```

这个文件回答：

- operator 是否要启用它
- operator 配了什么

它不回答：

- 插件入口在哪
- 当前是否加载失败

### `PluginStatus` 真源

`runtime_data/plugins/<plugin_id>/status.json`

```json
{
  "plugin_id": "notebook",
  "phase": "loaded",
  "load_error": "",
  "registered_tools": ["take_note"],
  "updated_at": "2026-04-01T12:00:00Z"
}
```

这个文件回答：

- 实际运行结果
- 上一次 reconcile 的产物

它不回答：

- operator 想不想启用
- 这个 plugin 包本体长什么样

## 统一插件世界

这套模型最重要的一点，是把 builtin plugin 和 extension plugin 收到同一套对象模型里。

不要再有：

- “config plugin 一套规则”
- “目录 plugin 一套规则”
- “builtin plugin 又是第三套规则”

应该统一成：

- builtin 也是 `PluginPackage`
- extension 也是 `PluginPackage`
- 只是 `source_kind` 不同

这样 WebUI 看到的是统一的 plugin 资源列表，而不是三种来源各自拼装的结果。

## `plugin_id` 才是正式身份，不是 import path

一旦 plugin 成为正式资源，WebUI 和 control plane 就不应该再把 import path 当主身份标识。

`import_path` 是实现细节，不是 operator-facing identity。

正式身份应该是：

- `plugin_id`

比如：

- `ops_control`
- `notebook`
- `backend_bridge_tool`

而不是：

- `acabot.runtime.plugins.ops_control:OpsControlPlugin`
- `plugins.notebook:NotebookPlugin`

理由很简单：

- import path 会改名
- class 名会重构
- 操作者不应该承担 Python 模块结构的认知负担

`plugin_id` 一旦稳定，WebUI、磁盘真源、状态文件、日志和 API 全都能围绕一个 ID 说话。

## Reconciler 视角下的生命周期

`PluginReconciler` 的输入有三类：

- package catalog
- spec store
- 当前 runtime 已加载状态

输出只有一种：

- 让 actual state 收敛到 desired state

典型流程：

1. 扫描全部 `PluginPackage`
2. 读取全部 `PluginSpec`
3. 计算每个 plugin 的 desired state
4. 观察当前 manager 里的 loaded plugins
5. 做 diff：
   - package 存在 + spec enabled=true + actual 未加载 -> `load`
   - package 存在 + spec enabled=false + actual 已加载 -> `unload`
   - package / spec 改变 -> `reload`
   - spec 存在但 package 缺失 -> `mark_uninstalled`
6. 写回 `PluginStatus`

这样一来：

- API 不需要直接操纵 runtime internals
- UI 只改 spec
- runtime 只负责收敛

这就是 control plane 应有的结构。

## API 应该怎么长

不要只提供“plugin config list”这种弱接口。

应该提升成资源接口：

- `GET /api/system/plugins`
  - 返回 package + spec + status 的合并视图
- `GET /api/system/plugins/<plugin_id>`
  - 返回单个 plugin 的完整资源视图
- `PUT /api/system/plugins/<plugin_id>/spec`
  - 更新 enabled 与 config
- `POST /api/system/plugins/<plugin_id>/reconcile`
  - 只收敛一个 plugin
- `POST /api/system/plugins/reconcile`
  - 全量收敛
- `GET /api/system/plugins/<plugin_id>/status`
  - 查看运行状态与错误

注意，WebUI 的 primary action 应该是“改 spec”，而不是“直接调用 load / unload”。

这是产品边界上的巨大差别：

- 前者是 control plane
- 后者只是一个调试面板

## 对 WebUI 的直接收益

有了四对象模型后，Plugins 页可以非常清楚地表达三层信息：

- 安装信息：这个 plugin 来自 builtin 还是 extensions
- 意图信息：operator 想不想启用，配了什么
- 状态信息：是否已加载、失败原因是什么

UI 就可以自然长成：

- 列表页看概览
- 详情页编辑 spec
- 状态面板看 reconcile 结果

而不是一个只会勾选开关的列表。

## 和当前实现的关系

当前实现并不是完全推翻，而是可以作为兼容层逐步迁移：

### 现有可复用的部分

- `RuntimePluginManager` 已经具备 load / unload / reload 基础能力
- plugin 生命周期协议已经存在
- plugin config 的读取接口已经存在
- tool / hook / model slot 的注册逻辑已经存在

### 当前需要收窄的部分

- `runtime.plugins` 不应长期继续充当唯一 plugin spec 真源
- 顶层 `plugins.<plugin_name>` 不应长期继续作为唯一 config 落点
- `import_path` 不应继续作为 UI 主身份

### 推荐迁移路径

第一阶段：

- 引入 `PluginPackage` 扫描
- 目录插件变成正式 package catalog
- UI 先展示 package + status

第二阶段：

- 引入 `runtime_config/plugins/<plugin_id>/plugin.yaml`
- enable / disable / config edit 全部写 spec 真源

第三阶段：

- 引入 `PluginStatus` 持久化
- 加入 `PluginReconciler`
- API 和 WebUI 正式改为 spec/status 模型

第四阶段：

- `runtime.plugins` 与顶层 `plugins.<name>` 降为兼容迁移层
- 最终收口到 package/spec/status 三层真源

## 为什么这套特别适合 AcaBot

AcaBot 当前整个产品方向都在收一件事：

“WebUI 面向的是正式对象和正式真源，而不是若干零散实现细节。”

`session-owned agent` 已经是这条线。

plugin 如果也收成：

- 全局 package catalog
- operator-owned spec object
- runtime-owned status object

那整个系统会开始说同一种设计语言。

这比“给目录插件补一个开关”高级很多。

因为它不是局部修补，而是把 plugin 正式纳入 control plane 对象模型。

## 最后一句

这四对象模型的本质不是“抽象很多”，而是：

它把“是什么”“想怎样”“现在怎样”“怎么变成那样”拆开了。

一旦这四句话被拆开，plugin 控制面才会从“能用”变成“可信”。
