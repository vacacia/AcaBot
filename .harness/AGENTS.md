# AGENTS.md

## 项目概述
AcaBot 是一个 Python 3.11 的 agent runtime,负责把网关事件收进运行时,完成 session 决策、thread 执行、tool / skill / subagent 调度,并通过本地 HTTP API 提供 WebUI。
主线：Gateway -> RuntimeApp -> SessionRuntime -> RuntimeRouter -> ThreadPipeline -> Outbox。


## 目录指引
- 看`/home/acacia/AcaBot/.harness/progress.md`了解进度
- `.harness/use-claude-code.md`: 使用 claude code 来 review/explore, 可以减少上下文污染, 或提供不同的观点
  - claude: 提供不同观点; 干脏活; 速度极快, explore一定要使用
  - **当用户明确要求“让 Claude Code 去看/调研/对比”时，直接委托 Claude Code，不要先在本地铺垫一堆前置信息污染自己的上下文；只保留最小必要提示。**
  - subagent: 更聪明, 更贵, 但和你的思维方式一样(可能都忽视一些问题)
- `docs/00-ai-entry.md`: 包含项目的组件理解(如plugin, skill...是什么)
- 源码在 `src/acabot/`
- 主运行时逻辑在 `src/acabot/runtime/`
- 部署相关在 `deploy/`
- WebUI 在 `webui/src/`, `src/acabot/webui/` 是构建产物
- 运行时数据在 `runtime_data/`
- acabot 运行时的配置在 `runtime_config/`
- `.harness/failure-patterns` 是失败模式库, 犯的错误要写入进去, 并在下面留一句话的索引(30 字之内, 一句话本身就能成立，不依赖当前对话上下文);犯了错误无论大小, 总是立即记录进去, 以免后面忘记:
  - FP-001: fake agent不能替代真实LLM验收
  - FP-002: 异步E2E不能只等待消息数量
  - FP-003: 复用helper前先验证它的实际输出
  - FP-004: 给LLM的工具协议不能写成黑盒
  - FP-005: SQLite失败写入会毒死后续调度
  - FP-007: 用户明确要Claude调研时, 先委托再说
- 可以参考的项目在`/home/acacia/AcaBot/ref`下,主要是`ref/claude-code-sourcemap-main` 和 `ref/openclaw`


## 关键契约
- git
  - 有多个partner在修改代码, 所以:
  - **只允许提交自己修改的内容**
    - 禁止 `git add <目录>` 或 `git add .`
    - 只准 `git add <具体文件>`，一个一个文件确认
    - commit 前必须 `git status` 确认只有自己改的文件
  - **commit 信息不写 coauthor**
  - **绝对不要 `git reset --hard`**
  - **绝对不要在没确认的情况下执行 revert**
  - 如果不确定用户要commit哪些文件，先问清楚
- 项目未正式使用, 不需要考虑任何兼容设计(兼容旧的数据/配置), 那都是之前的错误, 留下来只会误导自己.只要能变得更好, 一起都是可以舍弃, 可以重构的.
    - 如果你重构了, 不要体现出"原来是怎么样的", 比如测试里用黑名单/白名单, 注释里写"不要xxx", 除非是避坑式注释
- 不要陷入打补丁的困境, 如果出现了问题, 先想为什么有这个问题?问题暴露出的是什么问题?架构不合理?需求没问清?
- 共享 SQLite 持久化一旦出现写失败, 先怀疑事务/锁是否已被污染; 先修锁污染和 schema 漂移, 再看上层 scheduler / runtime 表象
- **优雅**的解决问题, 设计令人惊叹的架构
- 工具的desc表示如何使用工具; system prompt里声明什么时候使用工具(`src/acabot/runtime/context_assembly`)
- 写文档, 记录错误, 甚至给工具写desc: 不要写"你会的", 你的知识永远都在, 只简洁的记录你不知道的
- 看见`source /home/acacia/AcaBot/.venv/bin/activate`什么都不用管, 继续你的任务, 那是系统自己发送的


## 编码与文档
- 任何文件/类/方法都要有 docstring, 使用直白的中文写注释, 避免黑话, 保持连贯流程易读
- 大文件用 `# region` 帮助定位, region后的字符尽可能少, 才能在缩略图里完整显示
- 目录名、文件名、方法名要直接表达语义,不要抽象缩写
- 做结构性改动时,同时更新相关文档

## webui
- `webui/` 是前端源码目录，只改这里的源码，不要手改 `src/acabot/webui/` 下的构建产物
- `src/acabot/webui/index.html` 和 `src/acabot/webui/assets/` 是 build 产物，不再提交进 git
- 前端改动后，本地验证用：`npm --prefix webui run build`
- 运行中的 8765 页面读取的是构建产物；开发环境下重载后优先用：`docker restart acabot`
- Docker 已负责在镜像构建时自动执行前端 build；不要把“手工提交 assets”当成流程的一部分

## 验证是否正确
### review
- claude code review 之后, 推荐启动子代理(搭配review的skill)去 review 你这次的代码 和 测试文件.
    - 不要使用 gpt-5.1 ~ gpt-5.3的模型, 使用 gpt5.4 mini 和 gpt5.4
    - review 的粒度是一个完整的 任务/功能/需求, 不要写一点就 review 一次

### 测试
- 简陋的测试文件什么都不能说明
- 任务/功能/需求的验收:
  - 完整的 E2E 测试
    - 测试账号: 使用`qq:user:1733064202`作为sender发送给bot, 或者在群聊 `qq:group:1097619430`里使用`qq:user:1733064202`作为sender发送给bot
      - 必须要真实的LLM响应, 工具的desc, system prompt也是设计的一环, fake agent/stub LLM说明不了问题; 
      - 如果LLM响应出现问题, 找用户换API; 
      - 如果LLM响应总是不符合预期, 可以让claude去检查payload(位于`runtime_data/debug/model_payloads`)
      - 给LLM的消息不允许出现具体的工具/参数名(因为没人聊天的时候会像写代码一样说出name和desc);
      - 禁止引导LLM, 例如定时任务要设置随机数检查LLM是否能看见定时任务的内容;例如文件可见性要设置一个随机数让LLM自己看见, 当作CTF测试
      - LLM没按预期做? -- 是你的desc和prompt引导有问题
    - 例如从伪造 event, 到 LLM 响应回复, 全部链路都要符合预期
    - 例如消息响应策略, 全部的消息类型, 每个消息类型的响应策略, 都要经过验证
    - 例如调度功能, 要模拟event让llm创建定时任务(每种类型都要有), 并观察是否成功执行
  - 覆盖 任务/功能/需求 方方面面
  - 查看日志来评估自己的任务是否符合预期的执行了(日志内容不全?代码就在这,去补充日志信息)
  - 没有完整日志作为证据, 不允许结束, 不允许找用户汇报结果, 继续测试

### webui
- WebUI 的验收标准:
  - 用 playwright 截图验证, 确保布局合理;每次结束汇报都带着截图路径来(并且确认自己看过截图)
  - 用 playwright 完整的操作页面的全部流程
  - 在真实运行环境做验证, 禁止使用虚假的临时的测试环境

### 部署/容器
- 部署改动后运行：`cd deploy && docker compose -f compose.yaml -f compose.dev.yaml config`
- **绝对不要重启 / recreate / stop `acabot-napcat`**
  - 禁止使用会把整个 compose 项目一起处理的命令，例如：
    - `docker compose -f compose.yaml -f compose.dev.yaml up -d --build`, `docker compose restart`, `docker compose down`
  - 只允许针对 `acabot` 单独操作：
    - 开发环境热更新后优先用：`docker restart acabot`
    - 需要 compose 命令时只准：`docker compose -f compose.yaml -f compose.dev.yaml up -d --no-deps acabot`
    - 需要重建镜像时只准：`docker compose -f compose.yaml -f compose.dev.yaml up -d --build --no-deps acabot`
- 查看容器 acabot 和 acabot-napcat 的日志
- 因为容器挂载的文件权限问题可以`sudo chown`


## harness
```
.harness/
├── AGENTS.md                    ← 系统提示词层
├── GOLDEN_PRINCIPLES.md          ← 架构约束
├── features.json                 ← 功能追踪
├── progress.md                   ← 进度文件
├── failure-patterns/             ← 失败模式库
│   ├── FP-001.md
│   ├── FP-002.md
│   ├── FP-003.md
│   ├── FP-004.md
│   └── FP-005.md
├── skills/                       ← 自定义 Skills
├── scripts/                      ← 确定性工具
│   ├── check-architecture.js
│   ├── validate-env.sh
│   └── run-e2e.sh
└── CHANGELOG.md                  ← Harness 自身的变更日志
```



### 功能列表（JSON 格式）
示例:
```json
{
  "features": [
    {
      "id": "auth-001",
      "description": "用户可以用邮箱和密码注册",
      "priority": 1,
      "status": "passing",
      "verification": "POST /api/auth/register 返回 201 + JWT"
    },
    {
      "id": "order-001",
      "description": "用户可以创建新订单",
      "priority": 2,
      "status": "failing",
      "verification": "POST /api/orders 返回 201 + 订单 ID"
    }
  ]
}
```