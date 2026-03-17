# WebUI 和控制面

如果你的任务是“做控制面板”“补一个配置页”“让 WebUI 能操作某个运行时能力”，先看这一篇。

这块不是一个纯前端页面工程，而是一条完整链路。

## 总体结构

现在的链路是:

`webui/app.js -> RuntimeHttpApiServer -> RuntimeControlPlane -> RuntimeConfigControlPlane / runtime state`

对应文件:

- `src/acabot/webui/index.html`
- `src/acabot/webui/app.js`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/snapshots.py`
- `src/acabot/runtime/control/ui_catalog.py`
- `src/acabot/runtime/control/model_ops.py`
- `src/acabot/runtime/control/workspace_ops.py`
- `src/acabot/runtime/control/reference_ops.py`
- `src/acabot/runtime/control/config_control_plane.py`

## 前端这边是什么状态

`app.js` 现在已经不是“只展示一个小页面”的程度了，而是一个相对完整的本地控制台。

从页面目录能看出当前重点页包括:

- Dashboard
- Approvals
- Bot / Subagents
- Prompts
- Sessions
- Model Providers / Presets
- Gateway
- Runtime
- Plugins
- Workspaces
- References

这意味着如果你做 WebUI 新功能，最好先判断它应该挂在哪个现有页面体系里，而不是随手再起一套散的入口。

## `RuntimeHttpApiServer`

这个文件做两件事:

1. 提供本地 HTTP API
2. 可选托管静态 WebUI

特点:

- 用的是 Python 自带 `ThreadingHTTPServer`
- API 走 `/api/*`
- 静态文件默认从 `src/acabot/webui` 提供

### 加 API 时通常要改哪里

1. `handle_api_request()`
2. 需要时补 `RuntimeControlPlane` 方法
3. 如果涉及配置真源，再补 `RuntimeConfigControlPlane`

后台维护面现在也沿这条链路暴露最小只读接口:

- `/api/backend/status`
- `/api/backend/session-binding`
- `/api/backend/session-path`

第一阶段这些接口只暴露 backend 是否已接线、canonical session binding、binding 文件路径和当前后台模式状态, 不镜像 backend transcript, 也不引入 operation/artifact 列表。

这里的 `configured` 语义要注意: 现在它表示“真实 runtime 已经构造出 configured backend session service, 并且后台入口 / `ask_backend` / control plane 都会按 enabled backend 行为工作”, 不是“bridge 对象存在”这么弱的条件。

很多人只在 `http_api.py` 加个分支就完了，结果后面控制面逻辑越来越脏。正常做法还是把业务放回 control plane。

backend 这块当前已经这样做了: `http_api.py` 只提供 `/api/backend/*` 适配, 真正的 configured/session path/binding/status 聚合仍在 `RuntimeControlPlane`。

## `RuntimeControlPlane`

这是运行时运维入口。

它关心的是:

- 当前状态
- 当前配置快照
- 运行时对象查询
- plugin reload
- approvals
- runtime / memory / thread / run 可视化

它不直接等于配置真源，也不该把所有 YAML 读写细节都塞自己身上。

现在这一层内部也已经继续拆开了:

- `control_plane.py` 只保留 `RuntimeControlPlane` 本体和少量组装逻辑
- `snapshots.py` 放 control plane 返回给 WebUI / API 的轻量快照类型
- `ui_catalog.py` 放 WebUI 表单选项常量和目录选项 helper
- `model_ops.py` 放模型注册表相关控制面操作
- `workspace_ops.py` 放 workspace / sandbox / computer override 相关控制面操作
- `reference_ops.py` 放 reference 检索和写入相关控制面操作

所以如果你只是要改状态返回结构，优先看 `snapshots.py`；如果只是要改 WebUI 下拉框和选项枚举，优先看 `ui_catalog.py`，不要第一反应就去给 `control_plane.py` 继续加体积。

## `RuntimeConfigControlPlane`

这个文件才是很多“配置页”背后的真源读写层。

它处理的东西很多:

- profiles
- prompts
- binding rules
- inbound rules
- event policies
- filesystem 配置目录
- 热刷新相关注册表

### 判断一个 WebUI 功能改哪里

#### 只是展示运行时状态

优先改 `RuntimeControlPlane`。

#### 要读写持久配置

优先改 `RuntimeConfigControlPlane`。

#### 两者都要

前后都得碰。

## WebUI 新面板怎么加

建议按这个顺序:

1. 先确定数据源
   - 运行时状态
   - 配置真源
   - 两者结合
2. 先补后端接口
3. 再补前端页面状态和表单
4. 最后补导航入口和帮助文字

原因很简单: 这套 WebUI 的难点通常不在 DOM，而在“你到底在改运行时状态，还是在改配置真源”。

## 这块最常见的坑

### 1. 只改 `app.js`

页面看着能填了，但没有真实落盘或热刷新。

### 2. 把“当前状态”和“持久配置”混成一个接口

短期省事，长期会让页面行为非常难解释。

### 3. 忘了哪些改动需要重启

有些配置可以热刷新，有些改完只是写回文件。WebUI 文案最好讲明白，不要让用户误会“保存即生效”。

## 如果要做“WebUI 控制面板”

你给的优先级里 WebUI 是最高的，所以这里单独说一下。

最稳的办法不是先画 UI，而是先回答三件事:

1. 面板操作的是运行时状态，还是配置真源
2. 改完是否需要热刷新
3. 操作结果应该立刻在哪个页面能看到

常见落点:

- 新增只读面板: `RuntimeControlPlane + http_api + app.js`
- 新增配置编辑面板: `RuntimeConfigControlPlane + http_api + app.js`
- 新增动作按钮: 还要看是否需要触发 runtime service

## 建议的后端风格

尽量保持现在这种分层:

- `http_api.py` 只做 HTTP 适配
- `control_plane.py` 做运行时操作和状态聚合
- `config_control_plane.py` 做配置真源和热刷新

别把 YAML 读写、状态聚合、路由分发全堆进 `http_api.py`。

## 读源码顺序建议

1. `src/acabot/runtime/control/http_api.py`
2. `src/acabot/runtime/control/control_plane.py`
3. `src/acabot/runtime/control/snapshots.py`
4. `src/acabot/runtime/control/ui_catalog.py`
5. `src/acabot/runtime/control/model_ops.py`
6. `src/acabot/runtime/control/workspace_ops.py`
7. `src/acabot/runtime/control/reference_ops.py`
8. `src/acabot/runtime/control/config_control_plane.py`
9. `src/acabot/webui/app.js`
10. `src/acabot/webui/index.html`
