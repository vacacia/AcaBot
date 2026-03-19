# skill 

1. `skill` 在 AcaBot 里到底应该是什么
2. 当前实现里哪些地方是脏的、该整套删掉
3. 后续应该用什么方式重新落地 `skill`

先讲结论：

> `skill` 不应该再承担任何 subagent delegation 语义。
>
> `subagent` 是内部 agent，`skill` 是能力包，这两者不是同一层概念。
>
> `skill` 不一定必须通过 tool 实现；更合理的方向是把它保持成“按需加载的能力包”，同时通过稳定的可见路径解决 sandbox 和 workspace 的隔离问题。

## 1. 这次要删掉的错误设计是什么

当前最脏、也最该整套删掉的，是这套旧语义：

- `skill assignment` 里带 `delegation_mode`
- `skill assignment` 里带 `delegate_agent_id`
- `delegate_subagent` 还能通过 `skill_name -> assignment -> delegate_agent_id` 间接路由
- 系统里还存在“delegated skills”这种半 skill、半 subagent 的中间概念

这套设计的问题不是实现细节，而是概念本身就不干净。

它把两件本来应该分开的事绑在了一起：

- `skill` 是什么能力
- `subagent` 是谁来执行

一旦这两件事绑在一起，系统就会越来越难解释：

- `skill` 到底是能力包、工具，还是委派入口？
- `subagent` 到底是内部 worker，还是某种“被 skill 指向的执行后端”？
- profile 配的是 skill 可见性，还是 subagent 路由规则？

所以这里不适合修修补补，而适合**整套删干净**。

## 2. `skill` 应该是什么

`skill` 最适合被理解成：

> 一个按需加载的能力包。

它至少可以包含：

- `SKILL.md`
- `references/`
- `scripts/`
- `assets/`

它的职责不是“自己成为一个执行主体”，而是：

- 给模型一套专门任务说明
- 给模型一组工作步骤
- 给模型一些按需读取的参考资料
- 必要时再配合脚本和资源完成工作

所以：

- `skill` 不是 `subagent`
- `skill` 不是 delegation policy
- `skill` 不是内部 worker
- `skill` 也不一定必须是独立 tool

更准确地说：

- `subagent` 是 **agent**
- `skill` 是 **capability package**

这是后续所有实现选择的前提。

## 3. `skill` 一定要通过 tool 实现吗

不一定。

从实现方式上看，至少有三种路线。

### 方案 A：像 pi 那样，prompt 暴露摘要，模型自己按需读取

大致做法：

- 启动时扫描各个 skills 文件夹，拿到 `name + description`
- system prompt 里只放可用 skill 的摘要
- 模型任务匹配时，再用通用 `read` 去读完整 `SKILL.md`
- 之后按相对路径继续读 `references/`、执行 `scripts/`、使用 `assets/`

#### 优点

- `skill` 保持成真正的能力包，不会被压扁成函数列表
- 只有摘要常驻上下文，完整说明按需加载，比较省 token
- `references/`、`scripts/`、`assets/` 这类目录能力接得最自然
- `skill` 和 `subagent` 的边界最容易保持干净

#### 缺点

- 更依赖模型自觉，不一定每次都会先读 `SKILL.md`
- 如果路径设计得不好，隔离和可见性会比较难控
- 纯文件读法的审计粒度不如显式 tool 清晰

### 方案 B：提供一个很薄的 skill loader helper

- `load_skill(name)`
- 或保留一个很薄的 `skill(name)`

它不负责把 `skill` 变成执行主体，只负责：

- 加载对应 `SKILL.md`
- 返回能力包正文
- 或把当前 skill 标记为已加载

后续的 `references/`、`scripts/`、`assets/` 仍然走通用文件/执行工具。

#### 优点

- 比纯 prompt + `read` 更稳定
- 模型不需要自己猜 skill 路径
- 权限、审计、可见性更容易统一控制

#### 缺点

- 会多出一个“skill loader”概念
- 如果继续把这个 helper 越做越胖，最后又容易变回“skill 路由器”

### 方案 C：一 skill 一 tool

例如：

- `skill__write_daily_report`
- `skill__summarize_group_chat`

#### 优点

- 最直接，最容易做可见性控制和审计

#### 缺点

- tool 列表很容易膨胀
- skill 的目录能力会被压扁
- 更像 runtime 私有函数，不像能力包


## 4. 真正要注意的不是“是否 tool 化”，而是“路径是否稳定”

如果只是把宿主机真实 skill 路径暴露给 bot，例如：

- `/home/.../skills/foo/SKILL.md`
- `/tmp/.../skills/foo/SKILL.md`

那后面一定会遇到这些问题：

- sandbox 隔离难做
- host / docker / remote backend 路径不一致
- 工作区切换后 skill 路径不稳定
- 模型学到宿主机物理路径细节，后续非常难收

所以问题不在于“bot 能不能自己 `read` skill”，而在于：

> bot 读到的是不是**稳定的可见路径**，而不是宿主机真实路径。

### 错误做法

- 直接把物理 skill 路径告诉模型
- 让模型记住宿主机上的真实目录结构

### 正确方向

应该给模型一个稳定的逻辑可见根，例如：

- `/skills/<skill_name>/SKILL.md`
- `/skills/<skill_name>/references/...`
- `/skills/<skill_name>/scripts/...`
- `/skills/<skill_name>/assets/...`

这样：

- sandbox 可以围绕 `/skills` 这一层做隔离
- workspace 切换时语义稳定
- host / docker / remote backend 都可以在底层各自映射
- 模型不需要知道真实物理路径

也就是说，真正关键的是：

> `skill` 的可见性应该建立在稳定的虚拟路径 / visible path 上，而不是建立在宿主路径上。

## 5. 对 AcaBot 的落地结论

AcaBot 对 `skill` 的实现，直接采用 **方案 A**：

#### 方案 A：prompt 暴露摘要 + 模型自己 `read /skills/...`

做法：

- 启动时扫描 skills，拿到 `name + description`
- system prompt 里只放 skill 摘要
- 模型需要时自己读 `/skills/<name>/SKILL.md`
- 后续继续按相对路径读 references / 跑 scripts / 用 assets

这就是当前确定的方向，不再额外引入 `load_skill(name)` 这类 helper，也不把 skill 做成“一 skill 一 tool”。



## 6. 如果现在就开始删，应该怎么做

原来是 `AgentProfile.skill_assignments: list[SkillAssignment]`，一个 `SkillAssignment` 里既有 `skill_name`，又夹带 `delegation_mode` 和 `delegate_agent_id`，runtime 里还保留 `skill_name -> assignment -> delegate_agent_id` 这条旧路；最后要改成 `AgentProfile.skills: list[str]`，skill 只表示“当前 agent 能看到哪些能力包”，subagent 只表示“当前 agent 能委派给哪些内部 agent”，两条线彻底断开。

具体改法是一条直线：先删除 `SkillAssignment` 这个类型本身，把 profile、配置解析、快照、control plane、WebUI 全部从 `skill_assignments` 改成纯字符串 `skills` 列表；然后删除所有 skill-based delegation 代码，让 `SubagentDelegationBroker` 只接受 `delegate_agent_id`，不再支持从 `skill_name` 推导 subagent；接着把 `delegate_subagent` 收成纯 subagent 工具，只保留 `delegate_agent_id + task + payload`，不再接受 `skill_name`；再把 `SubagentDelegationPlugin` 的接线条件改回 subagent 自己的规则，不再看 delegated skills；再把可见性分成两套独立规则，skill 可见性只决定 prompt 里出现哪些 skill 摘要，subagent 可见性只决定 prompt 里出现哪些 subagent 和 `delegate_subagent` 能调哪些 agent。

skill 的使用路径也一起收口成方案 A：启动时扫描 skills，只把 `name + description` 放进 system prompt，runtime 提供稳定的 `/skills/<name>/...` visible path，模型按需用 `read` 读取 `SKILL.md / references / scripts / assets`；最后把外围口径一起改干净，把旧的 skill delegation 字段从提示词、控制面、API、WebUI 全部删掉，并且把 `/skills/...` 下的文件访问补成 skill 语义审计，也就是原始日志里仍然记录 `read(path=...)`，但 runtime 额外归纳出 `skill_loaded(name)`、`skill_reference_read(name, path)` 这类事件。这样改完以后，原来“skill 是半能力包半委派入口”的结构就会消失，最后只剩两件清楚的事：skill 是能力包，subagent 是内部 agent。

