# progress.md

## 当前状态
- [x] 项目路径结构统一: filesystem-only，全 snake_case，三层分离（extensions/ / runtime_config/ / runtime_data/）
- [x] 文档清理完成: 删除 14 个冗余文档，合并记忆子系统文档，更新路径引用
- [x] wiki/ 合并完成: 子系统文档合并到编号文档（computer→12、sticky-notes/LTM→05、skill/subagent→18），wiki/ 已删除
- [x] 镜像完善: Dockerfile（Full）+ Dockerfile.lite，加装系统工具/字体/Node/Chromium/数据科学栈/媒体处理

## 最近变更
- `2026-03-27` 完成 lancedb-first long-term memory runtime
- `2026-03-29` ~ `2026-03-30` 系统页规划、session bundle source of truth、session-owned agent hard cut
- `2026-04-01` 优化 WebUI 与 long-term memory extraction / query planning
- `2026-04-02` 目录重构（deploy/、extensions/、runtime_config/、runtime_data/）
- `2026-04-02` 文档大清理：删除冗余文档，合并 17-* 到 05，更新 09 路径，更新 HANDOFF
- `2026-04-02` 镜像完善：Full（~2.5GB，Node/ffmpeg/pandoc/数据科学栈）+ Lite（~1GB，最小可用）双 Dockerfile

## 已知问题
- webui 设计不完整，缺少很多配置页面
- bot 掌握工具太少
- 日志过于简陋，重要信息显示不全面
    - 工具调用的过程无展示
    - LTM 记录过程
- LTM 数据库安全性
- Reference Backend 不再需要且设计不合理需要删除

## 下一步
- WebUI 配置页面补全
- 工具扩展
- 定时任务做成正式基础设施
- **统一 message 工具**（**方案已定**）
    - 使用此工具, 并填写了 text 参数, 那 LLM 要写 NO_REPLY 避免重复返回
    - 不使用此工具, LLM 返回的文本会直接发送出去, 不会有任何多余动作(引用/@/react/...), 也是默认的交流方式, bot仅在需要表达其他行为时使用工具
    - 一个工具统一 send / reply / react / recall / @ ...(待定)
    - 核心参数：`action`（干什么）、`text`（内容）、`target`（发给谁，省略=当前会话）
    - 可选参数：`reply_to`（引用）、`emoji`（reaction）、`media`（附件路径）、`render_as_image`（文转图）、`silent`（静默）
    - 工具层只表达意图，映射到现有 Action 对象 → Outbox → Gateway，不重新抽象平台差异
    - 解锁：主动文转图、跨会话发消息、emoji reaction、撤回、附件发送、回复引用控制
- **Playwright + Chromium**（**方案已定：镜像依赖 + Outbox 渲染函数**）
    - 不是 BrowserRuntime，不是 plugin，不是 builtin tool
    - 镜像层面：Docker 镜像加装 `playwright` + Chromium（和 git、字体一样是环境依赖）
    - bot 使用：通过 bash 工具 `import playwright` 自己写脚本，按需截图/抓取/自动化
    - acabot 内部使用：Outbox 层一个 `render_markdown_to_image()` 工具函数，message 工具 `render_as_image=true` 时调用
    - 参考调研：`tmp/astrbot-text2img.md`、`tmp/openclaw-message-tool.md`


