# 2026-03-23 skill 行为和 docs/18-skill 对齐 todo

这次任务只有一个目标：

- 让 AcaBot 当前的 skill 行为，严格对齐 `docs/18-skill.md` 里 `## 2. skill 加载机制(以此为准)`。

已经拍板的前提：

- 以 `docs/18-skill.md` 为准
- 项目内 skill 和全局 skill 同名时，**项目优先**
- 前台继续走 Work World 路径，所以返回给模型的 skill 基目录使用 `/skills/<skill_name>`
- 这次先把 skill 行为改正，不顺手扩成别的功能

---

## 现在这条线的真实情况

当前代码里已经有三块东西：

1. `SkillCatalog`
   - 会读 skill 目录
   - 会拿到 `skill_name / description / root_dir / skill_md_path`

2. prompt 里的 skill 摘要
   - `ModelAgentRuntime._build_system_prompt(...)` 会把可见 skill 摘要拼进 system prompt

3. builtin skill tool
   - 当前还是 `skill(name=...)`
   - 返回值现在基本只是 `SKILL.md` 正文

这说明当前系统已经有 skill 的目录、摘要和读取入口。
接下来要做的是把这三部分收成和 `docs/18-skill.md` 一样的形状。

---

## 最终形态

改完以后，skill 这一条线应该长这样：

1. runtime 先扫描 skill 目录，建立统一 skill 清单
2. 发请求前，把 skill 名字和描述放进 system prompt 的 `<system-reminder>` 里
3. 模型看到的是 skill 名字和描述，不直接看到宿主机路径
4. 模型要用 skill 时，调用：
   - 工具名：`Skill`
   - 参数：`skill`
5. runtime 收到 `Skill(skill="...")` 后，自己去找对应的 `SKILL.md`
6. 返回内容固定包含三段：
   - `Launching skill: <name>`
   - `Base directory for this skill: /skills/<name>`
   - `SKILL.md` 正文
7. 后续 `references / scripts / assets` 继续由模型通过通用文件工具和 `bash` 自己读取

---

## 文件范围

### 1. skill 目录扫描和优先级

重点文件：

- `src/acabot/runtime/skills/loader.py`
- `src/acabot/runtime/skills/catalog.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/bootstrap/config.py`

这几处要一起表达一件事：

- runtime 会按固定顺序建立 skill 清单
- 至少覆盖：
  - 配置指定目录
  - 项目 skill 目录
  - 全局 skill 目录
- 同名时按“项目优先”收口成唯一一份 skill

如果现有 `FileSystemSkillPackageLoader` 已经不适合表达这件事，就把它拆成更清楚的多目录 loader，不要硬塞在一个 `root_dir` 里。

### 2. `Skill` builtin tool

重点文件：

- `src/acabot/runtime/builtin_tools/skills.py`
- `src/acabot/runtime/tool_broker/broker.py`

这里要改成：

- 工具名从 `skill` 改成 `Skill`
- 参数名从 `name` 改成 `skill`
- 对模型展示的 description 改成和 `docs/18-skill.md` 一致的说法
- 工具调用后的返回格式改成固定三段文本

### 3. prompt 里的 skill 摘要

重点文件：

- `src/acabot/runtime/model/model_agent_runtime.py`
- 可能还会碰到准备 `visible_skill_summaries` 的地方

这里要改成：

- skill 摘要放进 `<system-reminder>` 块
- 文案要明确说这是给 `Skill` 工具用的 skill 列表
- 继续只暴露 skill 名字和描述

### 4. `/skills/...` 和 skill 基目录的关系

重点文件：

- `src/acabot/runtime/computer/runtime.py`
- `src/acabot/runtime/computer/world.py`
- `src/acabot/runtime/computer/workspace.py`

这里主要是确认，不一定每个文件都要改：

- `Base directory for this skill: /skills/<skill_name>` 这句话说出来之后
- 当前 `/skills/...` 路径确实能继续读到同一份 skill 内容
- `references / scripts / assets` 路径都顺着这条线工作

---

## todo 1: 先写失败测试，锁定外部契约

先补测试，再写实现。

### 要补的测试

#### builtin skill tool

文件：

- `tests/runtime/test_builtin_skill_tools.py`

先补这些：

- `ToolBroker` 注册的是 `Skill`，不是 `skill`
- schema 参数名是 `skill`，不是 `name`
- `Skill(skill="sample_configured_skill")` 返回内容包含：
  - `Launching skill: sample_configured_skill`
  - `Base directory for this skill: /skills/sample_configured_skill`
  - `SKILL.md` 正文
- world 可见 skill 过滤仍然生效
- `/skills` root 隐藏时，`Skill` 工具不会出现在当前 run 里

#### prompt skill 摘要

文件：

- `tests/runtime/test_model_agent_runtime.py`
- 必要时 `tests/runtime/test_tool_broker.py`

先补这些：

- system prompt 里会出现 `<system-reminder>`
- reminder 里明确列出可见 skill 名字和描述
- 文案里明确写到 `Skill` 工具

#### skill 扫描优先级

文件：

- `tests/runtime/test_skill_loader.py`
- `tests/runtime/test_skill_catalog.py`
- 必要时新建专门测试文件

先补这些：

- 项目 skill 目录里的同名 skill 会覆盖全局 skill
- 不同目录的 skill 会一起进统一清单
- 最终 `SkillCatalog` 里每个 skill 只有一份生效记录

---

## todo 2: 改 skill 目录扫描，让它能表达“项目优先”

这一步完成后，runtime 应该能稳定拿到一份统一 skill 清单。

### 要做的事

- 给 skill loader 补多目录扫描能力
- 明确扫描顺序
- 明确同名 skill 的覆盖顺序
- 保持 `SkillPackageManifest` / `SkillPackageDocument` 这套数据还能继续用

### 这一步做完后的结果

- `SkillCatalog.reload()` 拿到的是一份已经按优先级收好的 skill 清单
- 后面的 prompt 摘要和 `Skill` 工具都只吃这份统一结果

---

## todo 3: 把 builtin skill tool 改成 `Skill(skill=...)`

### 要做的事

- `builtin_tools/skills.py` 改工具名
- 改参数 schema
- 改返回内容
- 保留当前 world 可见性判断
- 继续在读取成功后记录当前 thread 已经加载过这个 skill

### 这一步做完后的结果

- 前台模型看到的是 `Skill`
- 模型调用后，能直接拿到：
  - Launching 行
  - `/skills/...` 基目录
  - `SKILL.md` 正文

---

## todo 4: 把 prompt 里的 skill 摘要改成 18 里的样子

### 要做的事

- `ModelAgentRuntime._build_system_prompt(...)` 改成输出 `<system-reminder>`
- 文案明确说明这是 `Skill` 工具可用的 skill 列表
- skill 摘要继续按当前 run 可见性过滤

### 这一步做完后的结果

- 模型在真正调用 `Skill` 前，就知道当前有哪些 skill 可以用
- skill 目录会和工具入口配成一套，不再是一半在 prompt、一半在 description 里说不同的话

---

## todo 5: 确认 `/skills/...` 后续读取链真的通

### 要做的事

- 验证 `Skill(skill="x")` 返回 `/skills/x`
- 接着用 `read("/skills/x/SKILL.md")`
- 再继续读 `references / scripts / assets`
- 确认这条线在当前 Work World 下成立

### 这一步做完后的结果

- `Skill` 负责打开 skill 入口
- 通用文件工具负责继续读 skill 包里的其他材料
- skill 机制和 computer 的当前世界路径模型合在一起了

---

## todo 6: 同步文档

至少要同步这些：

- `docs/18-skill.md`
- `docs/00-ai-entry.md`
- `docs/01-system-map.md`
- `docs/19-tool.md`
- `docs/HANDOFF.md`

### 文档里要写清楚的点

- skill 的正式工具名是 `Skill`
- 参数名是 `skill`
- prompt 先暴露 skill 摘要
- 返回内容包含 `/skills/<skill_name>` 基目录
- 项目 skill 和全局 skill 同名时，项目优先
- 当前 skill 行为已经和 `docs/18-skill.md` 第 2 节对齐

---

## 建议执行顺序

1. 先补失败测试
2. 再改 skill 扫描和优先级
3. 再改 `Skill` builtin tool
4. 再改 prompt reminder
5. 再做 `/skills/...` 贯通验证
6. 最后同步文档

---

## 完成标准

改完以后，至少满足下面这些结果：

- runtime 能从多处目录建立统一 skill 清单
- 同名 skill 按“项目优先”生效
- 前台工具名是 `Skill`
- 参数名是 `skill`
- system prompt 里有给 `Skill` 工具用的 skill 摘要 reminder
- `Skill(skill="...")` 返回：
  - `Launching skill: ...`
  - `Base directory for this skill: /skills/...`
  - `SKILL.md` 正文
- 模型后续能通过 `/skills/...` 继续读取 references / scripts / assets
- 文档和代码一致
