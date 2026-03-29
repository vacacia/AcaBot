# 代码库关注点

## 技术债

- 仓库里仍然能看到明显的“新 runtime 与旧系统并存”痕迹。`src/acabot/runtime/bootstrap/`、`src/acabot/runtime/__init__.py` 和 `docs/15-known-issues-and-design-gaps.md` 都说明这条收口线还在继续。
- 旧式 plugin 风格代码仍然存在于 `plugins/notepad/`、`plugins/napcat_tools/`，而新的 runtime plugin 体系在 `src/acabot/runtime/plugins/`。这会增加阅读和维护成本。
- 前端源码和前端构建产物同时放在仓库里：源码在 `webui/`，构建后静态文件在 `src/acabot/webui/`。如果贡献者搞错修改入口，很容易产生漂移。

## 已知问题

- `docs/15-known-issues-and-design-gaps.md` 已明确写出：subagent 第一版还不支持递归委派、approval resume 和更长生命周期的 child run 语义。
- 同一份文档还指出：WebUI 日志目前只有最近一段内存窗口，不是完整历史检索。
- `src/acabot/runtime/control/http_api.py` 里留有注释，说明静态资源目录路径曾经是一个容易出错的边界。

## 安全注意事项

- 仓库里虽然主张通过环境变量注入密钥，但同时也存在 `runtime-env/napcat/`、本地 `config.yaml` 这类运行态目录，递归扫描时可能误碰权限受限或敏感状态文件。
- NapCat gateway 的 token 认证是可选的；如果 `gateway.token` 没配，`src/acabot/gateway/napcat.py` 的反向 WebSocket 边界会更弱。
- control plane 和 ops 命令具备修改运行时状态的能力，目前权限控制主要依赖配置里的 actor ID 白名单，而不是完整的独立认证体系。
- 生成文档或做仓库扫描时，需要避免把 provider env 值或本地运行时状态内容写进版本库。

## 性能瓶颈

- `src/acabot/runtime/pipeline.py` 自己就写明了一个已知限制：同一 thread 上并发 run 时，compaction 可能重复做，而不是 single-flight 共享结果。
- `src/acabot/runtime/memory/long_term_memory/storage.py` 说明第一版 LanceDB 实现优先保证正确性，更新路径可能会重写整张表。
- HTTP API 采用 `src/acabot/runtime/control/http_api.py` 里的 `ThreadingHTTPServer`，对本地控制面来说够用，但如果未来把它当高流量服务，会成为扩展性边界。

## 脆弱区域

- computer backend 语义还没有完全统一；`docs/15-known-issues-and-design-gaps.md` 已点出 exec/session 与文件读写还不总是共享同一套 backend 语义。
- sticky notes 当前是混合真源设计，这一点也在 `docs/15-known-issues-and-design-gaps.md` 里明确写了，说明产品语义和存储语义还在收敛中。
- session、subagent、filesystem catalog 这一整条链都还在快速演进，最近的设计文档和计划都集中在 `docs/superpowers/plans/`。
- 递归扫描仓库时，`runtime-env/napcat/` 下会遇到 permission denied 的文件，这对工具链和自动分析都属于真实噪音。

## 扩展上限

- 如果没有打开 SQLite 持久化，很多运行时状态会直接退回内存实现，相关装配逻辑在 `src/acabot/runtime/bootstrap/builders.py`。
- 日志历史目前受 `src/acabot/runtime/control/log_buffer.py` 的内存 ring buffer 限制。
- `src/acabot/runtime/subagents/execution.py` 的本地 subagent 执行更像 child run 机制，而不是可恢复、可长期运行的分布式任务系统。
- 当前部署形态本质上还是单进程、本地优先，围绕 `Dockerfile` 和 `runtime-env/compose.yaml` 组织。

## 风险依赖

- `lancedb` 是可选依赖，但一旦打开长期记忆就会成为硬依赖；缺失时 `src/acabot/runtime/bootstrap/builders.py` 会明确报错。
- `websockets` 对 NapCat gateway 是硬要求；`src/acabot/gateway/napcat.py` 虽然有保护，但没有它系统无法正式提供网关能力。
- `runtime-env/compose.yaml` 里 NapCat 镜像使用的是 `mlikiowa/napcat-docker:latest`，这对本地试验方便，但可复现性不如固定版本 tag。

## 缺失的关键能力

- 仓库中没有看到 `.github/workflows/` 之类的 CI 配置，所以版本库层面的自动化流程不可见。
- `webui/package.json` 没有专门的 JS/TS 测试命令，说明 WebUI 目前缺少独立前端测试体系。
- 一些设计缺口是明确“暂不解决”的，而不是漏掉，例如 subagent、computer backend 语义和日志持久化相关问题。

## 测试覆盖缺口

- 前端覆盖主要还是源码级和 API 契约级，没有浏览器层面的真实交互覆盖。
- 真实 NapCat 集成更多是靠协议测试和 docker wiring，缺少连接真实 QQ 环境的端到端验证。
- 运行态目录的权限、外部状态和部署细节，使得某些迁移风险很难在 unit test 层完全覆盖。
