# Phase 1: 系统页与运行时路径统一 - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Phase Boundary

这一 phase 负责把系统级共享配置和路径真源收进一个正式可用的控制面。范围包括 gateway 配置、共享管理员、filesystem catalog 扫描根、维护动作，以及“系统当前实际用了哪些配置路径和数据路径”的可说明总览。

它不负责重新设计首页状态卡，不负责 Session/模型/提示词/LTM 的正式编辑面，也不把系统页扩成所有领域配置的总入口。那些领域对象继续在各自页面里编辑，系统页只处理系统级共享配置，并在高级区说明它们实际落在哪。

</domain>

<decisions>
## Implementation Decisions

### 系统页范围与信息分层
- **D-01:** Phase 1 按既定页面归属实现：`系统` 页只编辑系统级共享配置，其他领域配置继续留在各自页面。
- **D-02:** `系统` 页正文的正式可编辑内容包含 gateway 配置、catalog 扫描根、共享管理员，以及单独的“重新读取配置”维护动作区。
- **D-03:** `系统` 页必须有高级区，用来展示技术细节和实际生效路径，但这些信息要用人话标签表达，不能直接把原始变量名或内部黑话扔到界面上。
- **D-04:** 高级区是只读的路径与真源总览，不是把所有内部状态原样 dump 到页面。它应帮助操作者回答“当前系统到底在用哪份配置、扫哪些目录、把数据写到哪里”。
- **D-05:** LTM、模型、提示词、Session 等领域对象继续在各自页面里编辑；系统页高级区可以说明它们的路径落点，但不抢这些页面的编辑权。

### 保存与生效语义
- **D-06:** 默认交互语义是“保存即尝试生效”，普通 WebUI 配置不额外要求用户点一次 apply。
- **D-07:** 对 gateway 这一类天然更偏重启生效的配置，系统应该仍然先保存，然后明确返回“已保存，需要重启后生效”。
- **D-08:** “重新读取配置”保留在独立维护区，主要处理用户手改磁盘文件后的同步需求，不应成为正常表单保存的前置步骤。

### 列表输入与交互形式
- **D-09:** 共享管理员和扫描根这类重复项输入不再用多行 textarea，而是改成“一次填一个”的列表编辑器。
- **D-10:** 主要交互是单项输入、快速确认添加、逐项删除。这样前端只需要对单个输入做即时校验，而不是等保存时再做整段 split / trim / filter。
- **D-11:** 批量导入可以作为辅助入口存在，但不是默认主交互；主交互仍然是单项列表编辑。

### 校验与错误反馈
- **D-12:** 前端负责它本地能可靠判断的轻量校验，例如必填项、数字范围、单项重复、空输入等。
- **D-13:** 前端不做宿主机文件系统“是否存在 / 当前是否可读”的权威判定。这类判断以后端和 control plane 为准，因为服务端才掌握真实路径解析和真实权限语义。
- **D-14:** 对 catalog 扫描根，界面需要展示解析后的实际目录预览，让操作者在保存前后都能看出系统会扫描到哪里。
- **D-15:** 错误和结果反馈采用“人话主结论 + 可展开技术细节”的形式，既方便普通操作者理解，也方便排障时看真实异常。
- **D-16:** 结果状态至少要区分：`已保存并已生效`、`已保存但需重启`、`保存失败未写入`、`已写入但应用/重载失败`。

### the agent's Discretion
- 高级区的卡片分组与命名文案。
- 批量导入是否在第一轮 Phase 1 实现里一起上线，还是作为同一实现波次里的次级项补入。
- 成功 / 警告 / 失败反馈在页面上的具体视觉形态，只要不改变上述状态语义即可。

</decisions>

<specifics>
## Specific Ideas

- 列表类输入参考本次讨论里的“修改列表项”思路：一项一项加，回车或确认快速加入，已加入的条目以离散行展示，并支持逐项删除。
- AcaBot 的理念允许展示技术细节，但这些细节必须被翻译成操作者看得懂的产品语言，而不是要求用户先读代码再猜字段含义。
- 系统页要帮助操作者在不看源码的情况下判断：“现在这台 AcaBot 实际加载的是哪份配置、哪些目录是 catalog 真源、哪些路径是运行时数据落点。”

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 项目边界与 phase 合同
- `.planning/PROJECT.md` — 项目级约束：WebUI 必须真的控制行为、路径需要可说明、系统页不应沦为占位壳
- `.planning/REQUIREMENTS.md` — `SYS-01`、`SYS-02`、`SYS-03`、`OPS-02` 是本 phase 的正式要求
- `.planning/ROADMAP.md` — Phase 1 目标、成功标准和 UI hint
- `.planning/STATE.md` — 当前阶段焦点和上下文延续信息

### 页面与产品语义
- `webui-pages-draft.md` §系统 — 系统页的页面骨架、模块边界、哪些内容应放正文/高级区
- `webui-pages-draft.md` §首页 — 首页承担状态展示，系统页不应把状态信息抢回来

### 控制面与配置真源语义
- `docs/08-webui-and-control-plane.md` — WebUI 到 control plane 的分层、配置页与状态页的职责区别、热刷新/重启语义
- `docs/09-config-and-runtime-files.md` — 配置查找顺序、filesystem-backed 真源、运行时数据目录、哪些改动更可能热刷新或需要重启
- `docs/01-system-map.md` — runtime、control plane、WebUI 的整体边界和接线位置

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `webui/src/views/SystemView.vue`：已经有系统页路由和卡片布局壳，但目前仍是状态页，需要扩成 Phase 1 的正式控制面。
- `webui/src/views/AdminsView.vue`：已经接好了 `/api/admins` 的加载与保存链路，可以复用其数据流和错误处理骨架，但交互需要从 textarea 改成单项列表编辑。
- `webui/src/lib/api.ts`：现有 `apiGet` / `apiPut`、缓存失效与持久 GET 缓存都可以复用，不需要另起一套页面私有请求层。
- `tests/runtime/test_webui_api.py`：已经覆盖 `/api/filesystem/config`、`/api/admins` 等控制面接口，是 Phase 1 后端契约测试的主要落点。

### Established Patterns
- WebUI 配置面遵循 `webui/src/*.vue -> RuntimeHttpApiServer -> RuntimeControlPlane -> RuntimeConfigControlPlane` 这条链；配置写入应继续留在 control/config 层，而不是让前端直接猜真源。
- 当前前端页面统一使用 `ds-*` 设计系统类和 `loading / saveMessage / errorMessage` 这种轻量状态组织方式。
- `RuntimeConfigControlPlane` 是配置真源读写与 reload 语义的正式归属；`http_api.py` 应保持薄适配层，不承载业务规则。

### Integration Points
- `src/acabot/runtime/control/http_api.py`：已经有 gateway / filesystem config / admins / reload-config 接口，可以在这里补 Phase 1 需要的新 payload 或新的只读总览接口。
- `src/acabot/runtime/control/control_plane.py`：适合聚合路径总览、应用结果状态等面向 WebUI 的控制面形状。
- `src/acabot/runtime/control/config_control_plane.py`：适合扩展“解析后的正式路径视图”、写入后的应用结果和 backend 权威校验。
- `webui/src/views/SystemView.vue`：会成为 Phase 1 的主前端落点。
- `webui/src/views/AdminsView.vue`：要么被系统页吸收，要么作为迁移时的实现参考。

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-system-runtime-paths*
*Context gathered: 2026-03-29*
