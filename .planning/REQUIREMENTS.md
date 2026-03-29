# Requirements: AcaBot

**Defined:** 2026-03-29
**Core Value:** 操作者必须能通过一个真实可用的 WebUI 稳定地理解并控制 AcaBot 的行为。

## v1 Requirements

### 系统与运行时路径

- [ ] **SYS-01**: 操作者可以通过系统页管理网关设置、管理员列表和 skill / subagent catalog 扫描根，并让变更作用到正式运行时真源
- [ ] **SYS-02**: runtime 配置、数据目录、catalog、workspace、sticky notes、长期记忆等正式路径通过统一解析链得到，而不是散落在代码里的硬编码字符串
- [ ] **SYS-03**: 操作者可以明确知道系统当前正式使用的配置路径和运行时数据位置，用于排障和维护

### 首页、日志与操作反馈

- [ ] **OPS-01**: 操作者可以在首页看到真实的 runtime、gateway 和 backend 状态，用来判断系统是否正常
- [ ] **OPS-02**: WebUI 在配置保存、校验失败、热刷新失败或控制面应用失败时，会向操作者返回明确错误而不是静默失败
- [ ] **OPS-03**: 日志页在当前 ring buffer 约束内保持可用，支持过滤、刷新、自动跟随和增量读取状态提示

### 模型与提示词

- [ ] **MODEL-01**: 操作者可以通过模型供应商页管理 provider 连接配置，并让变更作用到正式 model registry
- [ ] **MODEL-02**: 操作者可以通过模型预设页管理模型预设及其正式绑定关系，同时保持 model target registry 作为唯一正式模型来源
- [ ] **PROMPT-01**: 操作者可以通过提示词页管理提示词真源，并在删除时看到引用约束

### 扩展能力

- [ ] **EXT-01**: 操作者可以通过插件页管理插件启停和重载，并看到加载失败原因
- [ ] **EXT-02**: 操作者可以通过技能页浏览实际 skill catalog 内容，并且内容来自系统当前配置的扫描根
- [ ] **EXT-03**: 操作者可以通过 SubAgent 页浏览实际 subagent catalog 内容，并且内容来自系统当前配置的扫描根

### Session 行为管理

- [ ] **SESS-01**: 操作者可以通过 Session 页管理 session 的基础设置和事件响应 surface
- [ ] **SESS-02**: 操作者可以通过 Session 页管理上下文与工具可见性，并且这些设置基于当前 session/runtime 契约
- [ ] **SESS-03**: Session 页的行为配置在运行时能够被校验和生效，并且不会重新引入已废弃的旧私有模型字段

### 记忆与长期记忆

- [ ] **MEM-01**: 操作者可以通过记忆页稳定管理 sticky notes
- [ ] **LTM-01**: 操作者可以通过记忆页管理长期记忆的基础设置、模型绑定和专用提示词
- [ ] **LTM-02**: 操作者可以以产品字段视角查看长期记忆条目，而不是直接面对底层存储实现
- [ ] **LTM-03**: 长期记忆的提取 / 检索链路足够可靠、可解释，能支撑日常使用而不只是实验性质

## v2 Requirements

### 新用户上手

- **DOCS-01**: 新操作者可以通过 Quickstart 在本地启动 AcaBot、接入 NapCat、打开 WebUI 并完成首次配置
- **DOCS-02**: WebUI 关键页面具备最小必要的引导文案、空状态说明和上手提示

### 更深入的长期记忆与运维能力

- **LTM-04**: 操作者可以对长期记忆条目做更细粒度筛选、修订和验证
- **OPS-04**: 日志页支持超出内存窗口的历史检索或持久化日志查看

## Out of Scope

| Feature | Reason |
|---------|--------|
| WebUI 聊天工作区 | 当前后台控制台明确不做聊天工作区，优先把配置与运维面做实 |
| 单独的平台页面 | 平台相关配置已决定并入系统页，不再拆独立导航 |
| 插件市场 / 在线安装 / 版本管理 | 当前先把已有插件、skill、subagent 的可见性和控制面做实 |
| 将底层数据库或内部目录结构原样暴露给普通操作者 | 优先暴露产品化配置与条目字段，而不是把实现细节直接变成产品界面 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SYS-01 | Phase 1 | Pending |
| SYS-02 | Phase 1 | Pending |
| SYS-03 | Phase 1 | Pending |
| OPS-01 | Phase 2 | Pending |
| OPS-02 | Phase 1 | Pending |
| OPS-03 | Phase 2 | Pending |
| MODEL-01 | Phase 3 | Pending |
| MODEL-02 | Phase 3 | Pending |
| PROMPT-01 | Phase 3 | Pending |
| EXT-01 | Phase 4 | Pending |
| EXT-02 | Phase 4 | Pending |
| EXT-03 | Phase 4 | Pending |
| SESS-01 | Phase 5 | Pending |
| SESS-02 | Phase 5 | Pending |
| SESS-03 | Phase 5 | Pending |
| MEM-01 | Phase 6 | Pending |
| LTM-01 | Phase 6 | Pending |
| LTM-02 | Phase 6 | Pending |
| LTM-03 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-29*
*Last updated: 2026-03-29 after initialization*
