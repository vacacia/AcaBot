# 已知问题和设计缺口

这一篇不是架构蓝图，也不是功能说明。

它是给以后改代码的 AI 和维护者看的“问题清单”。

作用有两个:

1. 让人知道当前哪些地方已经看出有坑
2. 修完之后知道该回写哪些文档

这里不追求面面俱到，只记录已经比较明确、值得后续改动时优先注意的点。

## 使用方式

如果你准备改某个模块，先快速扫一眼这里，看有没有相关已知问题。

如果你修掉了这里的一条，别只改代码，也要顺手更新:

- 这一篇的状态
- 对应专题文档
- 必要时 `10-change-playbooks.md`

## 1. subagent 可见性和委派边界还不够严

### 现象

当前 `delegate_subagent` 支持直接传 `delegate_agent_id`。

这条路径会优先直接查 executor registry，而不是先严格经过当前 profile 的 skill assignment / delegation policy。

结果就是:

- 只要某个 subagent executor 已注册
- 当前 agent 又能看到 `delegate_subagent` 这个工具
- 就可能直接调用一个本不该对它开放的 subagent

### 为什么这是问题

这会削弱你在 WebUI / profile 层做的能力隔离。

系统表面上看起来是:

- bot 选择携带哪些 skill / subagent

但实际 direct delegation 路径可能比这个更宽。

### 相关代码

- `src/acabot/runtime/plugins/subagent_delegation.py`
- `src/acabot/runtime/subagent_delegation.py`

### 修复时通常要同步

- `06-tools-plugins-and-subagents.md`
- `02-runtime-mainline.md`
- 如果改变了配置语义，再看 `08-webui-and-control-plane.md`

### 建议状态

`open`

## 2. 外部 skill 目前只兼容目录格式，还没完全兼容运行时体验

### 现象

当前 skill package 已经能读:

- `SKILL.md`
- `references/`
- `scripts/`
- `assets/`

但 bot 现在真正能做的主要还是:

- 调 `skill(name=...)`
- 读取 `SKILL.md`

还没有完整做到外部 agent 那种:

- metadata 触发
- 先读 skill，再按需读 references
- 再按需执行 scripts

### 为什么这是问题

如果以后别人看文档，以为 AcaBot 已经“直接支持外部 skill”，会高估当前实现。

### 相关代码

- `src/acabot/runtime/skills.py`
- `src/acabot/runtime/skill_package.py`
- `src/acabot/runtime/skill_loader.py`
- `src/acabot/runtime/plugins/skill_tool.py`
- `src/acabot/runtime/computer.py`

### 修复时通常要同步

- `06-tools-plugins-and-subagents.md`
- `12-computer.md`
- `10-change-playbooks.md`

### 建议状态

`open`

## 3. computer 的文件操作和 backend 语义还没完全统一

### 现象

`exec/session` 会按 effective backend 走，但 `list/read/write/grep` 的路径语义仍偏向 host workspace。

也就是说，当前这两层能力还不是完全一套 backend 语义。

### 为什么这是问题

如果以后认真推进:

- docker backend
- remote backend
- 更严格的 sandbox

那“命令跑在哪”和“文件读写落在哪”可能会不一致。

### 相关代码

- `src/acabot/runtime/computer.py`
- `src/acabot/runtime/plugins/computer_tool_adapter.py`

### 修复时通常要同步

- `12-computer.md`
- `02-runtime-mainline.md`
- 如果影响工具暴露，再看 `06-tools-plugins-and-subagents.md`

### 建议状态

`open`

## 4. 附件总大小限制是在 staging 后才判定

### 现象

当前附件会先尝试下载 / 落地，然后再做累计大小检查。

超限后 snapshot 会标成失败，但已经落下来的文件不一定被立即清理。

### 为什么这是问题

长时间跑起来后，这会带来:

- workspace 膨胀
- 临时文件残留
- “逻辑上失败了，但磁盘已经写了”的不一致

### 相关代码

- `src/acabot/runtime/computer.py`

### 修复时通常要同步

- `12-computer.md`
- 如果影响图片 / 文件流程，再看 `10-change-playbooks.md`

### 建议状态

`open`

## 5. 文档和代码之间还没有自动一致性机制

### 现象

现在已经有“改代码要同步文档”的约束，但还是靠人工执行，没有自动检查。

### 为什么这是问题

时间一长，最容易失效的不是代码，而是文档。

### 相关范围

- `docs/`
- 未来可能是 CI / lint / pre-commit

### 可选改进方向

- 增加简单的文档变更检查
- PR / 改动模板里要求说明是否影响 docs
- 在 `tests` 或脚本里做最小结构校验

### 修复时通常要同步

- `00-ai-entry.md`
- 这一篇

### 建议状态

`open`

## 6. 已知问题不等于一定马上修

这里的条目不代表“现在就要重构一遍”，只代表:

- 这是当前比较清楚的真实缺口
- 后续改到相关模块时，优先顺手处理
- 至少别在文档里继续把它写成已经完美解决

## 维护规则

以后如果发现新的明确问题，建议按这个格式加条目:

1. 现象
2. 为什么是问题
3. 相关代码
4. 修复时通常要同步哪些文档
5. 当前状态

状态可以先简单用:

- `open`
- `in_progress`
- `resolved`
