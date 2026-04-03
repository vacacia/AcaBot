# GSD (Get Shit Done) 使用指南

GSD 是一个 Claude Code 的 meta-prompting 开发框架。它把"想法→需求→计划→执行→验证"这条链路自动化了，核心思路是：**让 AI 代理替你规划和执行，你只做决策**。

---

## 核心概念

### 产物体系

所有 GSD 产物住在 `.planning/` 目录下：

```
.planning/
├── PROJECT.md
├── REQUIREMENTS.md
├── ROADMAP.md
├── STATE.md
├── config.json
├── research/
│   ├── STACK.md
│   ├── FEATURES.md
│   ├── ARCHITECTURE.md
│   ├── PITFALLS.md
│   └── SUMMARY.md
├── codebase/
│   ├── STACK.md
│   ├── INTEGRATIONS.md
│   ├── ARCHITECTURE.md
│   ├── STRUCTURE.md
│   ├── CONVENTIONS.md
│   ├── TESTING.md
│   └── CONCERNS.md
└── phases/
    ├── 01-phase-slug/
    │   ├── 01-CONTEXT.md
    │   ├── 01-RESEARCH.md
    │   ├── 01-01-PLAN.md
    │   ├── 01-02-PLAN.md
    │   ├── 01-01-SUMMARY.md
    │   ├── 01-VERIFICATION.md
    │   └── 01-VALIDATION.md
    ├── 02-phase-slug/
    └── ...
```

### 项目级产物

| 文件 | 由谁生成 | 用途 | 谁读它 |
|------|---------|------|--------|
| **PROJECT.md** | `/gsd:new-project` | 项目的"宪法"——核心价值、约束、需求分类（Validated / Active / Out of Scope）、关键决策记录。每个阶段完成后自动演进（需求从 Active 移到 Validated）。 | 所有代理。roadmapper 从中推导阶段，planner/executor 对齐核心价值。 |
| **REQUIREMENTS.md** | `/gsd:new-project` | 结构化需求列表，每条带 `REQ-ID`（如 `AUTH-01`）。追踪每条需求被哪个阶段、哪个计划覆盖。确保需求不被遗漏。 | roadmapper（映射到阶段）、planner（覆盖检查）、verifier（验收对照）。 |
| **ROADMAP.md** | `gsd-roadmapper` 代理 | 阶段分解——每个 phase 有名称、目标、关联的 REQ-ID、成功标准。也包含进度追踪表。整个项目的执行骨架。 | 所有阶段命令。plan-phase 读阶段目标，execute-phase 读阶段信息，verifier 对照成功标准。 |
| **STATE.md** | GSD 自动维护 | 状态机——当前在哪个阶段、做到哪个计划、上次活动时间、累积的决策记录。断点恢复的关键：重跑任何命令时读这个文件确定从哪继续。 | 所有命令的第一件事就是读它。executor 更新位置，verifier 记录结果。 |
| **config.json** | `/gsd:new-project` 或 `/gsd:settings` | 工作流配置——模式（YOLO/交互）、粒度、并行开关、模型选择、各代理开关。控制整个框架的行为。 | 所有 orchestrator 命令读取配置决定行为。 |

### 项目级调研（research/）

由 `/gsd:new-project` 的研究阶段生成。4 个 researcher 代理并行产出，synthesizer 综合。

| 文件 | 内容 | 下游消费者 |
|------|------|-----------|
| **STACK.md** | 推荐技术栈、具体库版本、选型理由、不推荐什么及原因 | roadmapper（确定技术约束）、planner（选择具体库） |
| **FEATURES.md** | 同类产品的功能分析——哪些是 table stakes（不做用户就走）、哪些是 differentiator（竞争优势）、哪些是 anti-feature（故意不做） | 需求定义阶段（用户按类别选 v1 范围） |
| **ARCHITECTURE.md** | 同类系统的典型架构、组件边界、数据流、建议构建顺序 | roadmapper（决定阶段依赖顺序） |
| **PITFALLS.md** | 常见坑、预警信号、预防策略、应该在哪个阶段处理 | planner（避免已知陷阱）、checker（审查是否遗漏） |
| **SUMMARY.md** | 四份报告的综合摘要——关键发现、推荐决策、风险项 | 需求定义和路线图阶段的快速参考 |

### 代码库映射（codebase/）

由 `/gsd:map-codebase` 生成。4 个 mapper 代理并行扫描已有代码库。**Brownfield 项目专属**——帮助后续代理理解已有代码。

| 文件 | 内容 | 下游消费者 |
|------|------|-----------|
| **STACK.md** | 已有项目的实际技术栈、依赖版本、构建工具、配置方式 | new-project（识别已有技术约束）、planner（遵循已有栈） |
| **INTEGRATIONS.md** | 已有的外部集成——API、数据库、消息队列、认证等 | planner（新功能要和已有集成兼容） |
| **ARCHITECTURE.md** | 已有架构模式、层次、数据流、入口点、关键抽象 | planner/executor（遵循已有架构风格） |
| **STRUCTURE.md** | 目录布局、每个子目录的职责、文件命名惯例 | executor（知道新文件该放哪） |
| **CONVENTIONS.md** | 代码风格、命名规范、错误处理模式、异步模式、依赖注入方式 | executor（写出风格一致的代码） |
| **TESTING.md** | 测试框架、目录结构、mock 模式、fixture 用法 | executor（写测试时遵循已有模式） |
| **CONCERNS.md** | 技术债、安全隐患、性能问题、脆弱区域 | planner（规避已知问题区域）、verifier（检查是否引入新问题） |

### 阶段级产物（phases/XX-slug/）

每个阶段独立一个目录，包含该阶段从讨论到验证的完整生命周期。

| 文件 | 由谁生成 | 用途 | 谁读它 |
|------|---------|------|--------|
| **CONTEXT.md** | `/gsd:discuss-phase` | **意图传递的核心**——记录你在讨论阶段做的所有设计决策。分为"锁定决策"（你明确说了的）和"Claude 自由裁量"（你没说的，代理自行判断）。 | planner（按你的决策规划）、executor（按你的决策执行）、checker（验证计划尊重你的决策）。这是你的设计偏好不被代理"忘记"的保障。 |
| **RESEARCH.md** | `gsd-phase-researcher` | 阶段级技术调研——这个阶段具体要用什么库、有什么坑、相关代码在哪。比项目级研究更聚焦。 | planner（基于调研结果规划）、checker（验证计划是否采纳了调研建议）。 |
| **XX-NN-PLAN.md** | `gsd-planner` | 执行计划——每个 plan 包含：objective（目标）、frontmatter（wave、依赖、涉及文件）、tasks（具体任务列表，每个有 action/read_first/acceptance_criteria）、must_haves（验收必要条件）。一个阶段可能有多个 plan。 | executor（逐 task 执行并提交）。Plan 是 executor 的唯一指令来源，写得越具体执行质量越高。 |
| **XX-NN-SUMMARY.md** | `gsd-executor` | 执行报告——完成了哪些 task、创建/修改了哪些文件、遇到了什么偏差、自检结果。 | verifier（对照 plan 检查完成度）、orchestrator（spot-check 验证执行成功）。 |
| **VERIFICATION.md** | `gsd-verifier` | 验证报告——阶段目标是否达成、must_haves 逐条对照、自动检查结果、需要人工测试的项目。状态：passed / gaps_found / human_needed。 | orchestrator（决定阶段是否完成）。gaps_found 触发缺口修复循环。 |
| **VALIDATION.md** | `/gsd:plan-phase` | Nyquist 验证策略——从 RESEARCH.md 的"验证架构"部分提取，定义每个需求的最低验证覆盖。确保验证不是事后补丁而是前置设计。 | planner（在 plan 里嵌入验证步骤）、verifier（对照验证策略检查覆盖度）。 |

### 代理分工

GSD 不是一个代理干到底，而是**按职能拆分**：

| 代理 | 职能 | 何时出场 |
|------|------|---------|
| `gsd-project-researcher` | 项目级调研（技术栈、特性、陷阱） | `/gsd:new-project` 的研究阶段 |
| `gsd-research-synthesizer` | 综合多份研究报告 | 4 个 researcher 完成后 |
| `gsd-roadmapper` | 从需求推导阶段路线图 | `/gsd:new-project` 的路线图阶段 |
| `gsd-phase-researcher` | 阶段级技术调研 | `/gsd:plan-phase` 的研究步骤 |
| `gsd-planner` | 写执行计划（PLAN.md） | `/gsd:plan-phase` 的规划步骤 |
| `gsd-plan-checker` | 审查计划质量 | `/gsd:plan-phase` 的验证步骤 |
| `gsd-executor` | 执行计划、写代码、原子提交 | `/gsd:execute-phase` |
| `gsd-verifier` | 验证阶段目标是否达成 | `/gsd:execute-phase` 完成后 |
| `gsd-codebase-mapper` | 扫描代码库生成结构文档 | `/gsd:map-codebase` |
| `gsd-debugger` | 系统化调试 | `/gsd:debug` |

### Wave 并行机制

计划（PLAN.md）通过 frontmatter 里的 `wave` 字段分组：

```
Wave 1:  Plan-01, Plan-02  ← 互不依赖，并行执行
         ↓ 等 Wave 1 全部完成
Wave 2:  Plan-03            ← 依赖 Wave 1 的产出
         ↓
Wave 3:  Plan-04, Plan-05  ← 依赖 Wave 2
```

同一 wave 内的 plan 通过 **git worktree 隔离**并行执行，wave 之间串行。

---

## 主流程

### 1. 初始化项目：`/gsd:new-project`

完整流程：**提问 → 研究 → 需求 → 路线图**

```
/gsd:new-project
```

**流程步骤：**

1. **Brownfield 检测**：如果检测到已有代码，会问你要不要先 `/gsd:map-codebase`
2. **深度提问**：问你想做什么，层层追问直到理解透彻
3. **写 PROJECT.md**：综合所有上下文，生成项目定义
4. **工作流配置**：选择模式（YOLO/交互）、粒度、并行、模型等
5. **项目级研究**（可选）：派 4 个 researcher 并行调研技术栈、特性、架构、陷阱
6. **定义需求**：按类别让你选择 v1 范围，生成 REQUIREMENTS.md（带 REQ-ID）
7. **生成路线图**：roadmapper 代理从需求推导阶段，生成 ROADMAP.md

**快速模式**：如果你已经有需求文档，可以直接喂进去：

```
/gsd:new-project --auto @prd.md
```

跳过提问，自动推导需求和路线图。

### 2. 映射代码库：`/gsd:map-codebase`

派 4 个并行代理扫描代码库，生成 7 个结构化文档：

```
/gsd:map-codebase
```

| 代理 | 产出 | 内容 |
|------|------|------|
| Tech | `STACK.md` + `INTEGRATIONS.md` | 语言、框架、依赖、外部 API、数据库 |
| Arch | `ARCHITECTURE.md` + `STRUCTURE.md` | 架构模式、数据流、目录布局 |
| Quality | `CONVENTIONS.md` + `TESTING.md` | 代码风格、命名、测试结构 |
| Concerns | `CONCERNS.md` | 技术债、安全隐患、脆弱点 |

**Brownfield 项目推荐在 `/gsd:new-project` 之前先跑这个。**

### 3. 讨论阶段：`/gsd:discuss-phase N`

在规划之前，和你交互式讨论某个阶段的实现细节：

```
/gsd:discuss-phase 1
```

产出 `CONTEXT.md`——记录你做的所有设计决策。后续 planner 和 executor 都会读这个文件，确保你的意图被准确传达。

### 4. 规划阶段：`/gsd:plan-phase N`

三步走：**研究 → 规划 → 验证**

```
/gsd:plan-phase 1
```

1. **Researcher** 调研这个阶段涉及的技术细节
2. **Planner** 写执行计划（PLAN.md），包含具体 task、文件列表、验收标准
3. **Plan Checker** 审查计划是否真的能达成阶段目标（最多修订 3 轮）

**常用参数：**

```
/gsd:plan-phase 1 --skip-research   # 跳过研究，直接规划
/gsd:plan-phase 1 --research        # 强制重新研究
/gsd:plan-phase 1 --gaps            # 只为验证失败的部分补计划
/gsd:plan-phase 1 --prd spec.md     # 从 PRD 文档直接生成上下文
```

### 5. 执行阶段：`/gsd:execute-phase N`

按 wave 并行派 executor 代理写代码：

```
/gsd:execute-phase 1
```

每个 executor：
- 在独立 worktree 里工作
- 逐 task 原子提交
- 写 SUMMARY.md 报告
- 遇到需要人工决策的地方会暂停（checkpoint）

执行完后自动派 **verifier** 验证阶段目标是否达成。

**常用参数：**

```
/gsd:execute-phase 1 --interactive  # 交互模式，逐 task 确认
/gsd:execute-phase 1 --wave 2       # 只执行 Wave 2
/gsd:execute-phase 1 --gaps-only    # 只执行缺口修复计划
```

### 6. 全自动：`/gsd:autonomous`

一口气跑完所有剩余阶段：

```
/gsd:autonomous
```

每个阶段自动走 discuss → plan → execute → verify，直到全部完成或遇到需要人工介入的问题。

---

## 工作流配置（config.json）

`/gsd:new-project` 时会让你选择，之后可以用 `/gsd:settings` 随时修改：

| 配置项 | 选项 | 说明 |
|--------|------|------|
| mode | yolo / interactive | YOLO = 自动审批，interactive = 每步确认 |
| granularity | coarse / standard / fine | 阶段粒度（3-5 / 5-8 / 8-12 个阶段） |
| parallelization | true / false | 同 wave 内的 plan 是否并行 |
| commit_docs | true / false | .planning/ 是否提交到 git |
| model_profile | quality / balanced / budget / inherit | 子代理用什么模型 |
| workflow.research | true / false | 规划前是否先调研 |
| workflow.plan_check | true / false | 计划写完是否审查 |
| workflow.verifier | true / false | 执行完是否验证 |

---

## 常用命令速查

### 项目生命周期

| 命令 | 用途 |
|------|------|
| `/gsd:new-project` | 初始化项目（提问→研究→需求→路线图） |
| `/gsd:map-codebase` | 映射代码库（brownfield 项目推荐先跑） |
| `/gsd:progress` | 查看当前进度和状态 |
| `/gsd:stats` | 项目统计（阶段数、需求数、git 指标） |

### 阶段开发

| 命令 | 用途 |
|------|------|
| `/gsd:discuss-phase N` | 讨论阶段实现细节 |
| `/gsd:plan-phase N` | 规划阶段（研究→计划→验证） |
| `/gsd:execute-phase N` | 执行阶段（并行写代码→验证） |
| `/gsd:verify-work N` | 手动验收测试 |
| `/gsd:autonomous` | 全自动推进所有剩余阶段 |

### 路线图管理

| 命令 | 用途 |
|------|------|
| `/gsd:add-phase` | 在路线图末尾加阶段 |
| `/gsd:insert-phase` | 在两个阶段之间插入紧急工作 |
| `/gsd:remove-phase` | 删除阶段并重编号 |

### 质量和调试

| 命令 | 用途 |
|------|------|
| `/gsd:debug` | 系统化调试，带持久状态 |
| `/gsd:review --phase N` | 请外部 AI 审查计划 |
| `/gsd:validate-phase N` | 补充验证覆盖 |
| `/gsd:audit-uat` | 审查所有待验收项 |

### 里程碑

| 命令 | 用途 |
|------|------|
| `/gsd:complete-milestone` | 归档当前里程碑 |
| `/gsd:new-milestone` | 开始新里程碑 |
| `/gsd:milestone-summary` | 生成里程碑总结 |

### 快捷操作

| 命令 | 用途 |
|------|------|
| `/gsd:quick` | 快速任务，跳过可选代理 |
| `/gsd:fast` | 极简任务，内联执行无子代理 |
| `/gsd:do [描述]` | 自动路由到合适的 GSD 命令 |
| `/gsd:next` | 自动推进到下一个逻辑步骤 |

### 会话管理

| 命令 | 用途 |
|------|------|
| `/gsd:pause-work` | 暂停工作，生成上下文交接文档 |
| `/gsd:resume-work` | 恢复上次暂停的工作 |
| `/gsd:session-report` | 生成本次会话报告 |
| `/gsd:health` | 诊断 .planning/ 目录健康状态 |

---

## 典型工作流

### Brownfield 项目（已有代码）

```
/gsd:map-codebase         # 1. 扫描代码库
/clear
/gsd:new-project          # 2. 初始化项目（会读取 codebase map）
/clear
/gsd:discuss-phase 1      # 3. 讨论第一阶段
/clear
/gsd:plan-phase 1         # 4. 规划
/clear
/gsd:execute-phase 1      # 5. 执行
# 重复 3-5 直到所有阶段完成
```

### Greenfield 项目（从零开始）

```
/gsd:new-project           # 1. 提问→研究→需求→路线图
/clear
/gsd:discuss-phase 1       # 2. 讨论
/clear
/gsd:plan-phase 1          # 3. 规划
/clear
/gsd:execute-phase 1       # 4. 执行
```

### 全自动模式

```
/gsd:new-project --auto @prd.md    # 从 PRD 自动初始化
# 自动链式推进所有阶段
```

### 快速修复

```
/gsd:quick                 # 带 GSD 保障但跳过可选代理
/gsd:fast                  # 最轻量，内联执行
```

---

## 关键设计原则

**每步都提交**：每个阶段的产物（PROJECT.md、PLAN.md、代码变更）都原子提交到 git。即使上下文窗口耗尽，产物也不会丢。

**代理隔离**：每个子代理拥有独立的上下文窗口。orchestrator 只传路径，不传内容。避免 token 污染。

**断点恢复**：重跑任何命令都会自动检测已完成的部分并跳过。`STATE.md` 追踪精确位置。

**`/clear` 很重要**：每个阶段性命令之间建议 `/clear` 清理上下文窗口，给下一步留出完整空间。

**CONTEXT.md 是意图传递的关键**：`/gsd:discuss-phase` 产出的决策记录会被所有后续代理读取。你的设计偏好通过这个文件精确传达给 planner 和 executor。
