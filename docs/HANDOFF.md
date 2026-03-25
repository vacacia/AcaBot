# 当前进展 Handoff

## 统一上下文装配与记忆主线

前台 runtime 现在已经把最终模型输入收口到 `ContextAssembler + PayloadJsonWriter`，`ctx.system_prompt` 和 `ctx.messages` 只表示最终结果，`RetrievalPlanner` 也已经收成 prepare-only；在这条主线上，这轮把长期记忆写入线真的接进来了：事实存储新增了 sequence-aware 增量读取，runtime 新增 `StoreBackedConversationFactReader` 和 `LongTermMemoryIngestor`，前台写入路径现在是 `RuntimeApp / Outbox -> mark_dirty(thread_id) -> ConversationFactReader -> LongTermMemoryWritePort`，而且 assistant message 事实会显式带上真实 `conversation_id`。
这次真正证明有效的是 `dirty_threads + 单 worker + 双游标 + 启动扫库补 dirty` 这一套，`mark_dirty()` 保持同步、best-effort，不拖垮前台主线；另外 worker 循环已经补掉了 `asyncio.Event` 的丢唤醒竞态，失败时也不会推进游标，`save_cursor()` 失败会被收成“允许下次重复 ingest、交给 LTM 自己去重”的受控分支。
事实层这次也顺手钉成了更硬的契约：`ChannelEventStore / MessageStore` 对同 UID 只接受幂等重复写入，不再允许静默改写既有事实，这样 sequence 游标语义才站得住；`MemoryBroker` 现在继续统一读取 `/self`、sticky notes 和 store-backed 长期记忆，`SoulSource` 实际管理的已经是 `/self/today.md + /self/daily/*.md`，pipeline 不再自己读文件拼上下文；当前 bootstrap 只支持可选注入 `LongTermMemoryIngestor`，还没有默认 LTM backend，所以后面继续做这块时，先看 `docs/17-3-memory-long-term-memory.md`、`src/acabot/runtime/memory/conversation_facts.py`、`src/acabot/runtime/memory/long_term_ingestor.py`，不要把长期记忆写入重新挂回 `ThreadPipeline` 收尾，也不要发明持久化 dirty 表。

## Sticky Note 重构设计

sticky note backend 这一轮已经真正落到代码里了：主对象统一成 `StickyNoteRecord(entity_ref, readonly, editable, updated_at)`，文件真源是 `StickyNoteFileStore`，服务层是 `StickyNoteService`，统一文本出口是 `StickyNoteRenderer`，retrieval 入口是 `StickyNoteRetriever`，bot 工具面已经只剩 builtin `sticky_note_read(entity_ref)` / `sticky_note_append(entity_ref, text)`，control plane / HTTP API 也已经围绕 `entity_ref` 和整张 record 工作。
这次真正删干净的是旧 sticky note 主线：`MemoryItem / MemoryStore / structured_memory / sticky notes plugin / sticky_note_put|get|list|delete` 已经退出 runtime 主线，planner/broker/retriever 现在统一走 `sticky_note_targets`，群聊默认 target 是发言人和当前对话容器，私聊默认 target 是发言人；当前 runtime 里还没一起全局改名的 `channel_scope`，在这条 sticky note 主线上暂时承担 `conversation_id` 的现实现达成。
如果后面继续接 sticky note，先读 [17-2-memory-stickynotes-refactor.md](/home/acacia/AcaBot/docs/17-2-memory-stickynotes-refactor.md)、[17-2-memory-stickynotes.md](/home/acacia/AcaBot/docs/17-2-memory-stickynotes.md)、[tmp-sticky-note-refactor-decisions.md](/home/acacia/AcaBot/docs/tmp-sticky-note-refactor-decisions.md)；第一篇讲目标形态，第二篇讲当前已落地代码现状，第三篇保留拍板细节。
## 2026-03-23 skill 对齐已经完成主线实现

这轮已经把 skill 主线改到和 `docs/18-skill.md` 第 2 节一致：runtime 现在由 `runtime.filesystem.skill_catalog_dirs` 控制扫描哪些 skill 根目录，相对路径算 project、`~` 和绝对路径算 user，扫描阶段先保留全部 metadata，prompt 注入和 `Skill(skill=...)` 真正读取时再按可见性和 `project > user` 选出最后那一份，返回里也会带 `Base directory for this skill: /skills/...`；另外, computer 内部那个容易撞名的单数字段也已经改成 `host_skills_catalog_root_path`，和 runtime 配置层彻底分开了，并且已经同步了 `docs/18-skill.md` 第 2 节后面的现状说明、`docs/19-tool.md`、`docs/01-system-map.md`、`docs/00-ai-entry.md`、`docs/09-config-and-runtime-files.md`、`docs/12-computer.md`、`docs/critical-architecture-issues.md`。
文档同步时有一个硬边界：`docs/18-skill.md` 的 `## 2. skill 加载机制(以此为准)` 不准再动，后续只能修改这一节后面的现状说明，并让别的活文档去对齐它。
如果后面继续接着做，先看 `docs/18-skill.md`、`docs/19-tool.md`、`docs/01-system-map.md` 和当前 skill 相关测试，继续沿现在这条主线扩文档或代码。

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
- `docs/19-tool.md`
- `docs/20-subagent.md`
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

原来的 `docs/06-tools-plugins-and-subagents.md` 现在已经拆成了 `docs/19-tool.md` 和 `docs/20-subagent.md`。`19` 优先讲清 tool / builtin tool / plugin / skill 的当前边界，`20` 单独讲 subagent 的运行方式和边界，不再把这两条线揉在一起。

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

- `docs/19-tool.md`
- `docs/20-subagent.md`
- `docs/12-computer.md`
- `docs/todo/2026-03-22-builtin-computer-tools-and-pi-alignment.md`
- `docs/HANDOFF.md`

## 如果后面继续看这块，先看哪里

建议按这个顺序：

1. `docs/12-computer.md`
2. `docs/19-tool.md`
3. `src/acabot/runtime/computer/runtime.py`
4. `src/acabot/runtime/builtin_tools/computer.py`
5. `tests/runtime/test_computer.py`
6. `tests/runtime/test_builtin_tools.py`

## 当前收尾状态

这轮 builtin computer tools 和 pi 对齐，已经可以按完成处理。
接下来如果还继续动，就不是补主线缺口了，而是继续打磨或扩能力。
