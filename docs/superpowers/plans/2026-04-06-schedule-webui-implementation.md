# Schedule WebUI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `conversation_wakeup` scheduler 落地独立 `/schedules` WebUI，支持创建、删除、启停，并展示创建时间、最近一次执行时间、下一次执行时间。

**Architecture:** 后端先补齐 scheduler 的状态模型与 WebUI API，让“任务本身”具备可管理、可观察的稳定门面。前端独立在 `/schedules` 页面消费专用 API，页面视觉与布局交给 Claude + Impeccable 实现，但必须严格遵守本计划里的业务边界与字段契约。

**Tech Stack:** Python runtime control plane / scheduler / SQLite store；Vue 3 WebUI；现有 `webui/src/lib/api.ts`；pytest + WebUI API tests + browser automation/screenshot。

---

## 文件结构

### 后端
- Modify: `src/acabot/runtime/scheduler/contracts.py`
  - 给 `ScheduledTaskInfo` / `ScheduledTaskRow` 补齐 `created_at` / `updated_at` / `last_fired_at`
- Modify: `src/acabot/runtime/scheduler/store.py`
  - 扩展 SQLite schema 与 CRUD
  - 支持 list all / enable / disable / update fire metadata
- Modify: `src/acabot/runtime/scheduler/scheduler.py`
  - 支持 enable / disable
  - 触发时记录 `last_fired_at`
  - 恢复启用时重算下一次触发时间
- Modify: `src/acabot/runtime/scheduler/service.py`
  - 暴露 create / list / enable / disable / delete 的 conversation_wakeup 门面
  - 提供稳定序列化结构给 WebUI
- Modify: `src/acabot/runtime/control/control_plane.py`
  - 暴露 schedules 页面所需控制面方法
  - 明确 `owner = conversation_id` 的页面级门面语义
- Modify: `src/acabot/runtime/control/http_api.py`
  - 新增 `/api/schedules/conversation-wakeup*` 路由
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
  - 把 `ScheduledTaskService` 注入 control plane
- Modify: `src/acabot/runtime/__init__.py`
  - 必要时补 export

### 前端
- Modify: `webui/src/router.ts`
  - 新增 `/schedules`
- Modify: `webui/src/components/AppSidebar.vue`
  - 新增入口
- Modify: `webui/src/lib/api.ts`
  - 若需要，补 cache invalidation 前缀
- Create: `webui/src/views/SchedulesView.vue`
  - Claude + Impeccable 负责页面主体实现

### 测试
- Modify/Create: `tests/runtime/test_scheduler_service.py`
  - enable / disable / metadata
- Modify/Create: `tests/test_scheduler.py`
  - scheduler runtime 行为
- Modify/Create: `tests/runtime/test_webui_api.py`
  - schedules API
- Create: 前端视图相关测试（若仓库已有对应模式则沿用）
- Create/Modify: 浏览器自动化 / 截图验收脚本或测试

---

### Task 1: 扩展 scheduler 数据模型与 store

**Files:**
- Modify: `src/acabot/runtime/scheduler/contracts.py`
- Modify: `src/acabot/runtime/scheduler/store.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/runtime/test_scheduler_service.py`

- [ ] **Step 1: 先写失败测试，锁定新元数据字段与持久化行为**
  - 覆盖：
    - 新建任务后可读到 `created_at` / `updated_at`
    - 初始 `last_fired_at is None`
    - 任务触发后 `last_fired_at` 被写回
    - store 能读写这些字段

- [ ] **Step 2: 运行聚焦测试，确认当前失败**
  - Run: `PYTHONPATH=src uv run pytest tests/test_scheduler.py tests/runtime/test_scheduler_service.py -q`
  - Expected: 新字段相关断言失败

- [ ] **Step 3: 最小实现 contracts + store**
  - 为任务快照与 DB 行增加字段
  - 扩展 SQLite schema
  - 补齐 row <-> object 映射

- [ ] **Step 4: 回跑聚焦测试直到通过**
  - Run: `PYTHONPATH=src uv run pytest tests/test_scheduler.py tests/runtime/test_scheduler_service.py -q`

- [ ] **Step 5: 提交阶段性修改**

### Task 2: 实现 scheduler enable / disable / fire metadata

**Files:**
- Modify: `src/acabot/runtime/scheduler/scheduler.py`
- Modify: `src/acabot/runtime/scheduler/store.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/runtime/test_scheduler_service.py`

- [ ] **Step 1: 写失败测试，锁定启停语义**
  - 覆盖：
    - disable 后任务不触发
    - enable 后同一 `task_id` 恢复
    - `enabled=false` 时 API 侧 `next_fire_at = null`
    - enable 后 `next_fire_at` 重新计算到未来
    - `cron` / `interval` 从“现在”重算下一次触发
    - `one_shot` 仅在原始 `fire_at` 仍在未来时允许恢复，过期则返回冲突错误
    - one-shot 成功触发后转成 disabled tombstone，而不是直接消失
    - 已经 dequeue 并开始执行的任务，即使随后 disable，也不会强行撤销本次执行

- [ ] **Step 2: 运行失败测试**

- [ ] **Step 3: 最小实现 scheduler 启停逻辑**
  - 新增 public enable / disable
  - worker 跳过 disabled
  - fire 后更新 `last_fired_at` / `updated_at`

- [ ] **Step 4: 回跑测试**

- [ ] **Step 5: 提交阶段性修改**

### Task 3: 补齐 ScheduledTaskService 的 WebUI 门面

**Files:**
- Modify: `src/acabot/runtime/scheduler/service.py`
- Test: `tests/runtime/test_scheduler_service.py`

- [ ] **Step 1: 写失败测试，锁定 service 能力**
  - 覆盖：
    - list conversation_wakeup tasks
    - enable / disable / delete
    - `owner = conversation_id`
    - WebUI 需要的序列化字段
    - `last_fired_at` 表示“已开始执行 callback”

- [ ] **Step 2: 运行失败测试**

- [ ] **Step 3: 最小实现 service 门面**
  - 保持对 `conversation_wakeup` 收口
  - 不泄漏 callback / raw scheduler 细节

- [ ] **Step 4: 回跑测试**

- [ ] **Step 5: 提交阶段性修改**

### Task 4: 接入 control plane 与 HTTP API

**Files:**
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 写失败测试，锁定 API 契约**
  - 覆盖：
    - `GET /api/schedules/conversation-wakeup`
    - `GET /api/schedules/conversation-wakeup?conversation_id=...&enabled=...&limit=...`
    - `POST /api/schedules/conversation-wakeup`
    - `POST /api/schedules/conversation-wakeup/{task_id}/enable`
    - `POST /api/schedules/conversation-wakeup/{task_id}/disable`
    - `DELETE /api/schedules/conversation-wakeup/{task_id}`
    - 非法 payload -> `400`
    - 未知 `task_id` -> `404`
    - expired disabled one-shot enable -> `409`
    - service unavailable -> `503`
    - 重复 enable / disable 的幂等行为
    - `note` 长度上限与 schedule 分支 shape 校验

- [ ] **Step 2: 运行失败测试**

- [ ] **Step 3: 最小实现 control plane + API 路由**
  - bootstrap 注入 service
  - control plane 对 scheduler 不可用显式抛出语义异常
  - http_api 把该异常稳定映射为 `503`
  - http_api 返回页面直接可用的数据结构

- [ ] **Step 4: 回跑 API 测试**

- [ ] **Step 5: 提交阶段性修改**

### Task 5: Claude + Impeccable 实现前端页面

**Files:**
- Modify: `webui/src/router.ts`
- Modify: `webui/src/components/AppSidebar.vue`
- Modify: `webui/src/lib/api.ts`
- Create: `webui/src/views/SchedulesView.vue`

- [ ] **Step 1: 我提供给 Claude 的明确约束**
  - 固定路由 `/schedules`
  - 单列表主结构
  - 支持创建、删除、启停
  - 支持选择已有会话 + 手填 conversation_id
  - 页面最终只向 API 提交一个 `conversation_id`
  - 只管理 `conversation_wakeup`
  - 时间展示按浏览器本地时区
  - 风格与布局由 Claude + Impeccable 自主决定

- [ ] **Step 2: 通过终端 `claude` 发起前端任务并要求直接回传 diff**
  - prompt 里明确：只做前端、遵守现有 API 契约、使用 `.impeccable.md` 设计上下文

- [ ] **Step 3: Claude 完成前端实现并返回 diff**

- [ ] **Step 4: 我审查 Claude 产出的业务契约与可维护性**
  - 核对 route / sidebar / API 路径
  - 核对字段名、错误分支、时间展示与本地搜索
  - 核对 schedules 页面读取不会被 3 分钟 GET cache 卡住
  - 核对不会越界做插件任务

- [ ] **Step 5: 合入前端代码并修补必要接线**

- [ ] **Step 6: 进行前端聚焦验证**
  - 构建 / 单测 / 页面加载


### Task 6: 全量回归与网页操作验收

**Files:**
- Test: `tests/runtime/test_scheduler_service.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/runtime/test_webui_api.py`
- Test: browser automation / screenshot artifacts

- [ ] **Step 1: 跑后端回归**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_scheduler_service.py tests/test_scheduler.py tests/runtime/test_webui_api.py -q`

- [ ] **Step 2: 跑前端页面与浏览器操作验收**
  - 至少覆盖：打开页面、创建、暂停、恢复、删除
  - 覆盖失败分支：网络错误 / 无效输入 / 过期 one-shot 恢复失败
  - 验证短周期任务的 `last_fired_at` 与 `next_fire_at` 会刷新

- [ ] **Step 3: 产出 1080p 截图**
  - 保存可复查 artifact

- [ ] **Step 4: 做重启恢复验证**
  - disabled 持久化任务在重启后仍保持 disabled
  - metadata 恢复后与启停前一致

- [ ] **Step 5: 若 live runtime 可用，验证页面创建出的真实任务被 scheduler 接收**
  - 至少查看任务列表 / API / 日志对应证据

- [ ] **Step 6: 汇总测试报告与截图，准备向用户汇报**
  - 不给“感觉完成”的口头结论
  - 必须附上实际命令、结果、截图、关键证据
