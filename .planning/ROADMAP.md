# Roadmap: AcaBot

## Overview

这一轮路线不是再往系统里盲目堆新能力，而是把已经存在的 runtime、control plane、WebUI shell 和记忆能力收成一个真实可操作、可维护、可对外上手的后台控制台。执行顺序上，先统一路径与系统级真源，再让各页管理内容真正生效，之后把 Session 和记忆面收回 WebUI，最后再把长期记忆从“最小可运行”提升到“日常可用”。

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: 系统页与运行时路径统一** - 收敛系统级配置、扫描根和运行时数据路径，建立正式真源
- [ ] **Phase 2: 首页、日志与全局反馈可用化** - 让首页和日志页成为真实可靠的运维入口
- [ ] **Phase 3: 模型与提示词控制面生效** - 打通 provider / model / prompt 页到正式配置链
- [ ] **Phase 4: 插件与 catalog 页面生效** - 让插件、技能、SubAgent 页连接真实运行态与目录真源
- [ ] **Phase 5: Session 行为管理回归 WebUI** - 让 Session 页重新成为正式行为配置入口
- [ ] **Phase 6: 记忆页与 LTM 配置面可用** - 把 sticky notes 和 LTM 配置面收成正式产品能力
- [ ] **Phase 7: 长期记忆可用性硬化** - 提升长期记忆链路质量、可解释性和日常可用度

## Phase Details

### Phase 1: 系统页与运行时路径统一
**Goal**: 收敛系统级配置、catalog 扫描根和运行时数据路径，让 WebUI 后续页面有稳定正式真源可写
**Depends on**: Nothing (first phase)
**Requirements**: [SYS-01, SYS-02, SYS-03, OPS-02]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 操作者可以从系统页编辑网关设置、管理员列表和 catalog 扫描根，并且这些变更进入正式运行时配置
  2. runtime 配置、数据目录、catalog、workspace、sticky notes、LTM 路径有统一解析链，不再依赖分散硬编码
  3. 操作者可以清楚知道当前系统实际使用的配置路径与数据位置
  4. WebUI 对保存失败、校验失败和应用失败给出明确反馈
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 1` to break down)

### Phase 2: 首页、日志与全局反馈可用化
**Goal**: 让首页和日志页真正承担运维入口，而不是只保留展示壳
**Depends on**: Phase 1
**Requirements**: [OPS-01, OPS-03]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 首页显示的 runtime、gateway 和 backend 状态来自真实控制面数据
  2. 日志页支持当前窗口内的过滤、刷新、自动跟随和增量读取状态提示
  3. 操作者可以仅通过首页和日志页快速判断系统当前是否处于可运行状态
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 2` to break down)

### Phase 3: 模型与提示词控制面生效
**Goal**: 打通模型供应商、模型预设和提示词页面到正式配置链，让这些页面成为可信入口
**Depends on**: Phase 2
**Requirements**: [MODEL-01, MODEL-02, PROMPT-01]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. provider 页面编辑后会更新正式 model registry 配置
  2. model 页面编辑后会更新正式 preset / binding 状态，并保持 model target registry 为唯一正式模型来源
  3. prompt 页面编辑后会更新正式提示词真源，并正确处理删除约束
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 3` to break down)

### Phase 4: 插件与 catalog 页面生效
**Goal**: 让插件、技能和 SubAgent 页面接入真实运行态与 catalog 真源
**Depends on**: Phase 3
**Requirements**: [EXT-01, EXT-02, EXT-03]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 插件页可以管理启停 / 重载，并清楚展示加载失败原因
  2. 技能页展示的内容来自系统当前真实扫描根与 catalog 结果
  3. SubAgent 页展示的内容来自系统当前真实扫描根与 catalog 结果
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 4` to break down)

### Phase 5: Session 行为管理回归 WebUI
**Goal**: 让 Session 页围绕新的 session/runtime 契约重新上线，并成为正式行为配置入口
**Depends on**: Phase 4
**Requirements**: [SESS-01, SESS-02, SESS-03]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 操作者可以通过 Session 页管理基础设置和事件响应 surface
  2. 操作者可以通过 Session 页管理上下文和工具可见性，且配置基于当前 session/runtime 契约
  3. Session 配置变更能够通过校验并作用到运行时，而不会把系统拉回旧私有模型路径
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 5` to break down)

### Phase 6: 记忆页与 LTM 配置面可用
**Goal**: 把 sticky notes 与长期记忆的配置、模型、提示词和条目查看面收成正式产品能力
**Depends on**: Phase 5
**Requirements**: [MEM-01, LTM-01, LTM-02]
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 记忆页可以稳定管理 sticky notes
  2. 记忆页可以管理长期记忆基础设置、模型绑定和专用提示词
  3. 长期记忆条目可以用正式产品字段视角查看，而不是直接暴露底层存储实现
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 6` to break down)

### Phase 7: 长期记忆可用性硬化
**Goal**: 提升长期记忆提取 / 检索链路的可靠性、可解释性和日常可用度
**Depends on**: Phase 6
**Requirements**: [LTM-03]
**UI hint**: no
**Success Criteria** (what must be TRUE):
  1. 长期记忆的提取 / 检索链路在日常使用中稳定可靠
  2. 操作者能理解 LTM 为什么写入、为什么命中、为什么没命中
  3. LTM 不再只是“能跑起来”的实验能力，而是可日常依赖的系统能力
**Plans**: 0 plans

Plans:
- [ ] TBD (run `$gsd-plan-phase 7` to break down)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. 系统页与运行时路径统一 | 0/0 | Not started | - |
| 2. 首页、日志与全局反馈可用化 | 0/0 | Not started | - |
| 3. 模型与提示词控制面生效 | 0/0 | Not started | - |
| 4. 插件与 catalog 页面生效 | 0/0 | Not started | - |
| 5. Session 行为管理回归 WebUI | 0/0 | Not started | - |
| 6. 记忆页与 LTM 配置面可用 | 0/0 | Not started | - |
| 7. 长期记忆可用性硬化 | 0/0 | Not started | - |
