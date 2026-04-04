# progress.md

## 当前状态
- [x] 项目路径结构统一: filesystem-only，全 snake_case，三层分离（extensions/ / runtime_config/ / runtime_data/）
- [x] 文档清理完成: 删除 14 个冗余文档，合并记忆子系统文档，更新路径引用
- [x] wiki/ 合并完成: 子系统文档合并到编号文档（computer→12、sticky-notes/LTM→05、skill/subagent→18），wiki/ 已删除
- [x] 镜像完善: Dockerfile（Full）+ Dockerfile.lite，加装系统工具/字体/Node/Chromium/数据科学栈/媒体处理
- [x] Reference Backend 删除完成: 旧 reference 子系统、旧插件和相关接线已经整体移除
- [x] Plugin Reconciler 落地: plugin_id / package / spec / status / host / reconciler 新体系已接通，WebUI 插件管理页已重写
- [x] Scheduler 落地: cron / interval / one-shot、持久化恢复、按 owner 清理都已接到 runtime
- [x] LTM 数据安全落地: 写入串行化、备份、启动校验、优雅降级已补齐
- [x] Logging & Observability 落地: 结构化日志、run context、WebUI 日志字段展示已补齐
- [x] Unified message tool 落地: `message` 统一 surface、`SEND_MESSAGE_INTENT`、跨会话发送、reaction / recall、附件发送已接通
- [x] Playwright render chain 落地: render service、artifact path、lazy browser、bootstrap 注入、shutdown 回收已接通
- [x] cross-session continuity 收口: Outbox 现在会基于 delivery action + `source_intent` 自动生成 facts / working memory 摘要，真实 `message.send` 已能把内容写回 destination thread

## 最近变更
- `2026-03-27` 完成 lancedb-first long-term memory runtime
- `2026-03-29` ~ `2026-03-30` 系统页规划、session bundle source of truth、session-owned agent hard cut
- `2026-04-01` 优化 WebUI 与 long-term memory extraction / query planning
- `2026-04-02` 目录重构（deploy/、extensions/、runtime_config/、runtime_data/）
- `2026-04-02` 文档大清理：删除冗余文档，合并 17-* 到 05，更新 09 路径，更新 HANDOFF
- `2026-04-02` 镜像完善：Full（~2.5GB，Node/ffmpeg/pandoc/数据科学栈）+ Lite（~1GB，最小可用）双 Dockerfile
- `2026-04-03` 删除 Reference Backend，开始 v1 runtime infrastructure milestone
- `2026-04-03` 完成 Plugin Reconciler、Scheduler、LTM Data Safety、Logging & Observability 四大基础设施 phase
- `2026-04-03` ~ `2026-04-04` 完成 unified `message` tool、Outbox materialization、cross-session contract、render service、Playwright backend、bootstrap wiring
- `2026-04-04` 补齐 `OutboundMessageProjection` / `source_intent` continuity 链，修复真实 `message.send` 不写回 destination thread working memory 的缺口
- `2026-04-04` 文档同步：runtime mainline、data contracts、memory、gateway、milestone summary、phase verification 一起补齐
- `2026-04-04` 按 `gsd-plan-milestone-gaps` 把 milestone audit gap 正式拆成 Phase 05 / 06 / 07，回写 roadmap / requirements / state

## 已知问题
- webui 设计不完整，没有单独的 tools 面板，当前工具可见性和来源不够直观
- WebUI 非常卡
- milestone audit 已完成，gap closure phases 也已建好：Phase 05 / 06 负责补 GSD artifact 链，Phase 07 负责 render 可读性和 workspace / `runtime_data` 契约收口
- 真人验收发现 render 图片可读性仍有问题；quote + @、cross-session 真实 QQ 验收也还没形成正式记录
- 工具 desc 还可以继续打磨，减少模型误用和多余解释成本
- bot 的工作区指引 prompt 不够硬，仍会尝试在 `tmp/` 下工作
- bot 工作区与实际 `runtime_data` 的映射存在契约问题，需要单独修
- 群聊“仅回复 @ 和引用”失效，实际会回复全部消息；这不是本次 requirement，但属于需要单独收口的高严重度 bug

## 下一步
- 先计划并执行 gap closure phases：
  - `$gsd-plan-phase 05`
  - `$gsd-plan-phase 06`
  - `$gsd-plan-phase 07`
- 对不属于本次 requirement、但又不能放着不管的问题单独插 phase：
  - `$gsd-insert-phase 4 群聊回复策略 hotfix`
- gap closure phases 做完后，重新执行：
  - `$gsd-audit-milestone v1.0`
  - 通过后再 `$gsd-complete-milestone v1.0`
- WebUI 继续补：
  - 配置页面
  - tools 面板
  - 日志详情可读性
  - 性能优化
- 工具层继续扩：
  - tool desc 打磨
  - 更多高价值 builtin / plugin tools
  - 未来再考虑 schedule 管理 UI 和更多主动能力

---

## 备忘 / 停车场

- `_should_persist_action()` 为什么不是 session config 决定的
- bot 调用工具但不发消息时，是否要在 system prompt 里更明确地告诉模型
- 日志里工具调用详情的展开与染色
- tools 面板与当前 tool 可见性展示
- 容器里路径和 `runtime_data` 表达是否还需要更顺眼
- scheduler 的 WebUI 管理页
- subagent 相关体验和治理
