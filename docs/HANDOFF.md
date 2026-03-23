# 当前进展 Handoff

## 2026-03-23 文档同步继续推进

这轮又把六篇还带旧味道或缺少现状入口的活文档对到了当前代码：

- `docs/07-gateway-and-channel-layer.md`
- `docs/10-change-playbooks.md`
- `docs/12-computer.md`
- `docs/13-model-registry.md`
- `docs/14-reference-backend.md`
- `docs/16-front-back-agents-and-self-evolution.md`

这次主要修掉的是六类问题：

- `07` 里把 gateway 说得太单，漏了 `gateway/onebot_message.py`、`runtime/gateway_protocol.py`、`runtime/inbound/` 和 `RuntimeApp.handle_event()` 之后的实际主线
- `10` 里还在给旧入口和旧文件指路，比如 `webui/app.js`、旧 rule 线、旧 frontstage tool 名字，现在已经全部换成当前入口：`SessionRuntime`、`builtin_tools`、`ComputerRuntime`、`runtime/inbound/`、`control_plane / http_api`
- `12` 虽然大方向是对的，但这轮继续收紧成当前真相：前台只剩 `read / write / edit / bash`，`ComputerRuntime` 的入口、`/skills` 规则、附件 staging、控制面 workspace 能力、backend 分层都按现行代码重写了一遍
- `13` 里还把人往不存在的 `src/acabot/webui/app.js` 带，这轮已经换成当前真实会碰到的模型控制面入口：`model_ops`、`control_plane`、`http_api`、`config_control_plane`
- `14` 原来更偏“plugin + backend”两段式说明，这轮补上了现在已经存在的 `reference_ops`、`control_plane` 和 `/api/reference/*` 入口
- `16` 原来更多在讲方向，这轮补上了当前已经落地的 backend 地基：`BackendBridge`、`ask_backend`、管理员 `/maintain` / `!` 入口、canonical session binding 默认路径和 `PiBackendAdapter`

现在如果后面继续看平台接入、改动落点或 computer，先看这三篇新版本，不要再按旧文档里的入口和旧工具名找代码。

## 2026-03-22 文档同步已经补上

这轮除了代码收口, 还把几篇主文档按当前代码重新对齐了:

- `docs/00-ai-entry.md`
- `docs/01-system-map.md`
- `docs/02-runtime-mainline.md`
- `docs/03-data-contracts.md`
- `docs/04-routing-and-profiles.md`
- `docs/05-memory-and-context.md`
- `docs/06-tools-plugins-and-subagents.md`
- `docs/08-webui-and-control-plane.md`
- `docs/09-config-and-runtime-files.md`
- `docs/11-deployment-reference.md`
- `docs/15-known-issues-and-design-gaps.md`
- `docs/20-critical-architecture-issues.md`

这次文档同步主要修了三类过时内容:

- 旧 frontstage 工具面, 现在已经统一写成 `read / write / edit / bash`
- 旧 rule 系统说法, 现在统一回到 `SessionConfig + SessionRuntime + profile/prompt`
- 已经删掉的 adapter / plugin 文件路径, 现在都换成还存在的 builtin tool 或 runtime 入口

另外, `docs/02-runtime-mainline.md` 这一篇已经整篇重写, 不再沿用旧的 router + rule 叙事, 现在直接按 `RuntimeApp -> RuntimeRouter -> SessionRuntime -> ThreadPipeline -> AgentRuntime -> Outbox` 这条现行主线来讲。

`docs/03-data-contracts.md` 也已经整篇重写, 现在按“外部输入 / 会话决策 / 执行现场 / 持久化事实”这四层来整理当前契约, 不再把旧 rule 系统当成数据主线。

`docs/06-tools-plugins-and-subagents.md` 也已经整篇重写, 现在优先讲清楚 tool / builtin tool / plugin / skill / subagent 的当前边界, 不再把现状、未来设想和历史包袱揉在一起。

`docs/05-memory-and-context.md` 也已经整篇重写, 现在按“working memory / 事件事实 / 消息事实 / 长期记忆 / sticky notes / soul”这几层来讲, 并且已经改成当前 pipeline、retrieval planner、memory broker、structured memory 的真实链路。

如果后面继续改 WebUI / control plane, 先看现在这几篇文档, 不要再按旧的 `binding / inbound / event policy` 主线理解系统。

## 2026-03-22 builtin computer tools 和 pi 对齐已经收口

这轮最重要的结果已经稳定下来：

- core tool 已经不再靠 plugin 生命周期注册
- 前台 `computer` 工具面现在已经固定成：
  - `read`
  - `write`
  - `edit`
  - `bash`
- 前台已经不再暴露这些旧工具：
  - `ls`
  - `grep`
  - `exec`
  - `bash_open`
  - `bash_write`
  - `bash_read`
  - `bash_close`

## builtin tool 和 plugin 的边界

现在真正直接注册进 `ToolBroker` 的基础工具来源是：

- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`

`plugin` 现在主要表示外部扩展能力。
前台基础工具已经从 plugin 生命周期里拆出来了，所以 plugin reload 不会再把 `read / write / edit / bash` 一起带坏。

## computer 当前真相

现在真正干活的是：

- `src/acabot/runtime/computer/runtime.py`

前台 builtin surface 只是接线层：

- `src/acabot/runtime/builtin_tools/computer.py`

`ComputerRuntime` 现在已经有这组稳定入口：

- `read_world_path(...)`
- `write_world_path(...)`
- `edit_world_path(...)`
- `bash_world(...)`

其中：

- `read` 支持 `path / offset / limit`，文本分页，图片读取
- `write` 支持自动建父目录、覆盖写入、返回字节数
- `edit` 支持 `path / oldText / newText`，BOM、CRLF、fuzzy match、diff
- `bash` 支持 `command / timeout`

## `/skills/...` 现在的规则

这块这轮也已经收清楚了：

- `/skills/...` 的读写已经走 canonical skills 目录
- 不再写进 `skill_views/...` 副本
- 可见 skill 可以直接被 `read` 访问
- builtin surface 不再自己偷偷做 skill mirror 预处理
- 这些事情已经收回 `ComputerRuntime` 里处理

## `edit` 和 pi 当前版本的对齐点

收尾 review 里最容易争起来的是 `edit` 的 fuzzy 行为。
这轮已经重新核对过 pi 当前真正生效的版本：

- `@mariozechner/pi-coding-agent/dist/core/tools/edit.js`
- `@mariozechner/pi-coding-agent/dist/core/tools/edit-diff.js`

结论是：

- fuzzy 命中后，pi 当前版本确实会拿归一化后的整份文字做替换基底
- `Found N occurrences` 这一步，pi 当前版本也确实一直按 fuzzy 归一化后的文字计数

AcaBot 现在和 **pi 当前版本** 保持一致。
不要再被旧的 `packages/mom/src/tools/edit.ts` 带偏。

## 测试验证

这轮最后跑过的完整验证是：

- `PYTHONPATH=src pytest tests/runtime tests/test_main.py tests/test_config_example.py -q`
- 结果：`352 passed`

另外，`edit` 那两个最容易误判的 fuzzy 行为也单独重新跑过：

- `PYTHONPATH=src pytest tests/runtime/test_computer.py -q -k 'fuzzy_match_normalizes_other_lines_like_pi or exact_match_still_rejects_fuzzy_duplicates_like_pi'`
- 结果：`2 passed`

## 文档状态

这轮和当前代码对齐的文档主要是：

- `docs/06-tools-plugins-and-subagents.md`
- `docs/12-computer.md`
- `docs/todo/2026-03-22-builtin-computer-tools-and-pi-alignment.md`
- `docs/HANDOFF.md`

## 如果后面继续看这块，先看哪里

建议按这个顺序：

1. `docs/12-computer.md`
2. `docs/06-tools-plugins-and-subagents.md`
3. `src/acabot/runtime/computer/runtime.py`
4. `src/acabot/runtime/builtin_tools/computer.py`
5. `tests/runtime/test_computer.py`
6. `tests/runtime/test_builtin_tools.py`

## 当前收尾状态

这轮 builtin computer tools 和 pi 对齐，已经可以按完成处理。
接下来如果还继续动，就不是补主线缺口了，而是继续打磨或扩能力。