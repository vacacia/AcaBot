# WebUI 和控制面

WebUI 不是纯前端页面工程，而是一条完整链路：

```
webui/src/*.vue → vite build → src/acabot/webui/ → RuntimeHttpApiServer → RuntimeControlPlane / RuntimeConfigControlPlane → runtime state / 配置真源
```

## 关键文件

| 层 | 文件 |
|----|------|
| 前端源码 | `webui/src/`、`webui/src/router.ts`、`webui/src/views/`、`webui/src/components/` |
| 构建配置 | `webui/vite.config.ts` |
| 构建产物 | `src/acabot/webui/index.html`（RuntimeHttpApiServer 托管这里，不是手写源码） |
| HTTP API | `src/acabot/runtime/control/http_api.py` |
| 运行时控制面 | `src/acabot/runtime/control/control_plane.py`、`snapshots.py`、`ui_catalog.py`、`model_ops.py`、`workspace_ops.py`、`reference_ops.py` |
| 配置控制面 | `src/acabot/runtime/control/config_control_plane.py` |
| 日志 | `src/acabot/runtime/control/log_buffer.py` |

## 前端页面体系

当前 Vue + Vite 应用，重点页面包括：首页、Soul、记忆、管理员、模型供应商/模型、提示词、插件/技能/子代理、会话、系统、日志。新功能应先判断挂在哪个现有页面体系里，不要随手起散的入口。

改完 `webui/src/*.vue` 后必须跑 `npm --prefix webui run build`，RuntimeHttpApiServer 读的是 `src/acabot/webui/` 里的构建产物。

## RuntimeHttpApiServer

`runtime/control/http_api.py`，用 Python 自带 `ThreadingHTTPServer`。两个职责：提供 `/api/*` HTTP API，可选托管静态 WebUI。

加 API 时通常要改：`handle_api_request()` → 需要时补 `RuntimeControlPlane` 方法 → 涉及配置真源再补 `RuntimeConfigControlPlane`。业务逻辑放回 control plane，不要在 http_api.py 里堆。

### 后台维护接口

后台维护面沿同一条链路暴露最小只读接口：`/api/backend/status`、`/api/backend/session-binding`、`/api/backend/session-path`。第一阶段只暴露 backend 是否已接线、canonical session binding、binding 文件路径和后台模式状态，不镜像 transcript，不引入 operation/artifact 列表。

`configured` 的语义：runtime 已经构造出 configured backend session service，且后台入口、`ask_backend`、control plane 都按 enabled backend 行为工作——不是"bridge 对象存在"这么弱的条件。http_api.py 只提供 `/api/backend/*` 适配，真正的聚合在 RuntimeControlPlane。

### 主动发送接口

控制面现在提供 `POST /api/notifications`，用于从本地运维面主动发一条 bot 消息。请求体最小格式：

```json
{
  "conversation_id": "qq:user:1733064202",
  "text": "你的通知内容"
}
```

这条入口直接复用 `RuntimeControlPlane.post_notification()` 和 `Outbox`，消息会走正式 `Gateway -> NapCat` 出站链路，同时把成功送达的 assistant message 写进 `MessageStore`，目标 thread 也会追加一条 assistant working message。

### 日志接口

`InMemoryLogBuffer` 缓存最近一段 runtime 日志。`GET /api/system/logs` 返回 `items`、`next_seq`、`reset_required`，前端通过 `after_seq` 增量轮询。语义是"最近日志窗口"，不是完整历史日志检索。

### System 页面里的 render 默认配置

系统页（`webui/src/views/SystemView.vue`）现在有一块 **Render 默认配置** 面板，用来维护两个全局默认值：

- `width`
- `device_scale_factor`

保存动作走 `PUT /api/render/config`，读取当前值走 `GET /api/render/config`。System 页自己的统一快照 `GET /api/system/configuration` 也会返回 `render` 字段，方便前端一次性拉齐 gateway / render / filesystem / admins 等系统设置。

这两个值属于 runtime render 默认值，不是 session 级覆盖。WebUI 文案只承诺“保存并尝试生效”；最终是否清晰，仍以真实 QQ 客户端里的 render 可读性验收为准。

## RuntimeControlPlane

`runtime/control/control_plane.py`。运行时运维入口，关心当前状态、配置快照、运行时对象查询、plugin reload、approvals、runtime/memory/thread/run 可视化。不直接等于配置真源。

内部已拆分：

| 文件 | 职责 |
|------|------|
| `control_plane.py` | 本体和组装逻辑 |
| `snapshots.py` | 返回给 WebUI/API 的轻量快照类型 |
| `ui_catalog.py` | WebUI 表单选项常量和目录选项 helper |
| `model_ops.py` | 模型注册表控制面操作 |
| `workspace_ops.py` | workspace、sandbox、attachments、mirrored skills 控制面操作 |
| `reference_ops.py` | reference 检索和写入控制面操作 |

改状态返回结构看 `snapshots.py`，改下拉框和选项枚举看 `ui_catalog.py`，不要默认往 `control_plane.py` 加体积。

## RuntimeConfigControlPlane

`runtime/control/config_control_plane.py`。配置页背后的真源读写层，当前处理：profiles、prompts、gateway、render 默认值、runtime plugins、filesystem 配置目录、session-config 驱动的 reload。

### 判断一个 WebUI 功能改哪里

- **只展示运行时状态**：改 RuntimeControlPlane
- **要读写持久配置**：改 RuntimeConfigControlPlane
- **两者都要**：前后都得碰

## 新面板开发流程

1. 先确定数据源（运行时状态 / 配置真源 / 两者结合）
2. 先补后端接口
3. 再补前端页面状态和表单
4. 最后补导航入口和帮助文字

难点通常不在 DOM，而在"你到底在改运行时状态还是配置真源"。

## 后端风格

保持当前分层：http_api.py 只做 HTTP 适配，control_plane.py 做运行时操作和状态聚合，config_control_plane.py 做配置真源和热刷新。

## 常见问题

1. **只改 `webui/src` 没重新 build**：浏览器看到的还是旧页面。
2. **把"当前状态"和"持久配置"混成一个接口**：短期省事，长期让页面行为难解释。
3. **忘了哪些改动需要重启**：有些配置可以热刷新，有些只是写回文件。WebUI 文案要讲明白。

## 源码阅读顺序

1. `src/acabot/runtime/control/http_api.py`
2. `src/acabot/runtime/control/control_plane.py`
3. `src/acabot/runtime/control/snapshots.py`
4. `src/acabot/runtime/control/ui_catalog.py`
5. `src/acabot/runtime/control/model_ops.py`
6. `src/acabot/runtime/control/workspace_ops.py`
7. `src/acabot/runtime/control/reference_ops.py`
8. `src/acabot/runtime/control/config_control_plane.py`
9. `webui/src/router.ts`
10. `webui/src/views/`
11. `webui/src/components/`
