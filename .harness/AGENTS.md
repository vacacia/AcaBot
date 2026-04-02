# AGENTS.md

## 项目概述
AcaBot 是一个 Python 3.11 的 agent runtime，负责把网关事件收进运行时，完成 session 决策、thread 执行、tool / skill / subagent 调度，并通过本地 HTTP API 提供 WebUI。
主线：Gateway -> RuntimeApp -> SessionRuntime -> RuntimeRouter -> ThreadPipeline -> Outbox。


## 目录指引
- 先读 `docs/00-ai-entry.md`。
- Python 源码在 `src/acabot/`，主运行时逻辑在 `src/acabot/runtime/`。
- WebUI 开发只改 `webui/src/`，不要手改 `src/acabot/webui/` 构建产物。
- 运行时状态在 `runtime_data/`，配置在 `runtime_config/`，扩展在 `extensions/`。

## 关键契约
- 项目未正式使用, 不需要考虑任何兼容设计(兼容旧的数据/配置), 那都是之前的错误, 留下来只会误导自己.只要能变得更好, 一起都是可以舍弃, 可以重构的.
    - 如果你重构了, 不要体现出"原来是怎么样的", 比如测试里用黑名单/白名单, 注释里写"不要xxx", 除非是避坑式注释
- 不要陷入打补丁的困境, 如果出现了问题, 先想为什么有这个问题?问题暴露出的是什么问题?架构不合理?需求没问清?
- **优雅**的解决问题, 设计令人惊叹的架构


## 编码与文档
- 任何文件/类/方法都要有 docstring, 使用直白的中文写注释, 避免黑话, 保持连贯流程易读
- 大文件用 `# region` 帮助定位, region后的字符尽可能少, 方便在缩略图里显示完全
- 目录名、文件名、方法名要直接表达语义，不要抽象缩写。
- 详细编码规范以 `docs/00-ai-entry.md` 为准。
- 做结构性改动时，同时更新相关文档。

## 验证
- 在完成了 todo/task 后, 先不 commit, 立即启动子代理(搭配review的skill)去 review 你这次的代码 和 测试文件.
    - 不要使用 gpt-5.1 ~ gpt-5.3的模型, 没有 gpt5.4 mini 和 gpt5.4 聪明
    - review 的粒度是一个完整的任务, 不要写一点就 review 一次
- Python 改动后运行：`uv run pytest`
- WebUI 改动后运行：`cd webui && npm run build`
- 部署改动后运行：`cd deploy && docker compose config`
- 查看 acabot 和 acabot-napcat 的日志
- 如果这里的命令在当前仓库跑不通，先修正 AGENTS.md，不要留下失效命令。

## harness
```
.harness/
├── AGENTS.md                    ← 系统提示词层
├── GOLDEN_PRINCIPLES.md          ← 架构约束
├── features.json                 ← 功能追踪
├── progress.md                   ← 进度文件
├── failure-patterns/             ← 失败模式库
│   ├── FP-001.md
│   └── FP-002.md
├── skills/                       ← 自定义 Skills
│   ├── database-migration/
│   │   └── SKILL.md
│   └── deployment/
│       └── SKILL.md
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