
## v0.1 — 基础骨架

- [ ] **Task 1: 项目脚手架**
  - `pyproject.toml`, `src/acabot/__init__.py`, `src/acabot/main.py`, `tests/conftest.py`, `.gitignore`

- [ ] **Task 2: 类型定义 — event, action, hook types**
  - `src/acabot/types/` (`event.py`, `action.py`, `hook.py`), `tests/types/`

- [ ] **Task 3: ABC 接口层 — Gateway, Session, Store, Agent**
  - `src/acabot/{gateway,session,store,agent}/base.py`, `src/acabot/store/null.py`

- [ ] **Task 4: BotContext — 插件统一接口**
  - `src/acabot/plugin/context.py`, `src/acabot/plugin/base.py`, `src/acabot/config.py`

- [ ] **Task 5: NapCat Gateway 实现**
  - `src/acabot/gateway/napcat.py`, `tests/test_gateway.py`

**v0.1 验收标准：**
- [ ] `pip install -e ".[dev]"` 成功
- [ ] `python -m pytest tests/ -v` 全部 PASS
- [ ] 所有 ABC 接口定义完毕
- [ ] NapCat Gateway 能翻译 OneBot v11 消息为 StandardEvent
- [ ] BotContext 能通过 Null Object 正常运行

---

## v0.2 — 多轮对话

- [ ] **Task 6: InMemorySessionManager**
  - `src/acabot/session/memory.py`, `tests/test_session.py`
  - Session 只有 `session_key` / `messages` / `metadata` 三个字段

**v0.2 验收标准：**
- [ ] Session 按 session_key 隔离
- [ ] 同一 session_key 的多条消息共享上下文
- [ ] InMemorySessionManager 的 get_or_create / get / save 全部 PASS

---

## v0.3 — Agent + Hook + Pipeline

- [ ] **Task 7: LitellmAgent — LLM 调用 + Tool Loop**
  - `src/acabot/agent/agent.py`, `tests/test_agent.py`

- [ ] **Task 8: Hook 框架**
  - `src/acabot/hook/{base,registry}.py`, `tests/test_hook.py`

- [ ] **Task 9: Pipeline — 主线 + Hook 集成**
  - `src/acabot/pipeline.py`, `tests/test_pipeline.py`
  - 消息流：on_receive → pre_llm → LLM → post_llm → before_send → send → on_sent

- [ ] **Task 10: Main 入口 — 串联所有组件**
  - `src/acabot/main.py`, `config.example.yaml`
  - 从 config.yaml 读取值传入各组件, 消除硬编码:
    - `gateway.host` / `gateway.port` (当前硬编码 0.0.0.0:8080)
    - `gateway.timeout` (当前硬编码 10.0s)
    - `logging.level` (当前硬编码 INFO)

**v0.3 验收标准：**
- [ ] LitellmAgent tool calling loop 正常（mock 测试通过）
- [ ] Hook 优先级排序、abort 中断链、异常隔离
- [ ] Pipeline 完整消息流 PASS
- [ ] Main 入口能启动
- [ ] 全部测试 PASS

---

## v0.4 — 持久化 + 痛点解法 + 插件基础设施

### Phase 1: 基础设施

- [ ] **Task 11: SQLiteMessageStore — 消息持久化**
  - `src/acabot/store/sqlite.py`

- [ ] **Task 13: PluginLoader — 插件加载（含 schedules 遍历）**
  - `src/acabot/plugin/loader.py`

- [ ] **Task 14: ScheduleManager — 定时调度**
  - `src/acabot/scheduler.py`

- [ ] **Task 21: KVStore ABC + InMemoryKVStore**
  - `src/acabot/kv/{base,memory}.py`

- [ ] **Task 22: LLMProvider + LLMProviderRegistry**
  - `src/acabot/llm/{base,registry}.py`

- [ ] **Task 23: SQLiteMessageStore 增强 — query()/count()**
  - `src/acabot/store/sqlite.py`

### Phase 2: 内置 Hook

- [ ] **Task 15: GateHook — 门控过滤**
  - on_receive, p=10 | 解决痛点4

- [ ] **Task 18: MultimodalPreprocessHook — 多模态预处理**
  - on_receive, p=30 | 解决痛点3

- [ ] **Task 17: ContextCompressorHook — 上下文压缩**
  - pre_llm, p=80 | 解决痛点2

- [ ] **Task 19: ErrorFilterHook — 错误拦截**
  - post_llm, p=10

- [ ] **Task 16: MemoryArchiveHook — 消息归档**
  - on_sent, p=100

### Phase 3: 集成

- [ ] **Task 20: Main 入口更新 — 串联全部 v0.4 组件**

- [ ] **Task 24: 压缩型消息处理 — segment summary + 异步摘要（设计）**

- [ ] **Task 25: config.yaml llm_providers + main.py 组装**

- [ ] **配置分层 — 基础设施与行为配置解耦**
  - config.yaml 拆分为两层: 基础设施(gateway/端口/数据库路径, 绑定部署环境) + profile(模型/人设/插件配置, 绑定 bot 行为)
  - config.yaml 通过 `profile: "profiles/casual.yaml"` 指向行为配置文件
  - 切换 bot 性格/模型/插件只需改一行 profile 路径, 不碰基础设施配置

**v0.4 验收标准：**
- [ ] SQLite 存储正常（save/get_messages/query/count）
- [ ] 插件加载（setup → hooks → tools → schedules）
- [ ] 门控过滤（关键词/正则/require @bot）
- [ ] 上下文截断（token 预算 + 保留最近 N 条）
- [ ] 多模态预处理（图片/表情/视频 → 文字描述）
- [ ] 错误拦截（友好提示替换原始错误）
- [ ] KVStore 可用，LLMProviderRegistry 可用
- [ ] 集成测试全流程 PASS

---

## v0.5 — 记忆系统 + 上下文智能压缩 + Sandbox

### Phase 0: 设计审查修复

- [ ] **Task 26a: SQLiteKVStore — KVStore 持久化**
  - `src/acabot/kv/sqlite.py`
  - 支持 `update()` 原子读-改-写

- [ ] **Task 26c: 多模态预处理缓存**
  - 修改 MultimodalPreprocessHook，KVStore 缓存 URL→summary

- [ ] **Task 26d: 媒体引用短编号 — LLM 按需查看媒体详情**
  - 修改 MultimodalPreprocessHook，注册 `get_message_detail` tool

### Phase 1: 上下文智能压缩

- [ ] **Task 26: ContextCompressorHook 升级 — 分层压缩 + LLM 摘要**
  - `src/acabot/hooks/context_compress.py`
  - 三层压缩：tool 结果压缩 → 旧消息丢弃 → LLM 滚动摘要

### Phase 2: 记忆插件

- [ ] **Task 27: NotepadPlugin — 便签/基本信息**
  - `src/acabot/plugins/notepad/plugin.py`
  - 用户级 + 群级 KVStore 存储，pre_llm 注入 messages

- [ ] **Task 28: SimpleMemPlugin — 长期记忆摘要**
  - `src/acabot/plugins/simplemem/plugin.py`
  - on_sent 后台摘要，pre_llm 门控检索注入

### Phase 3: Docker Sandbox

- [ ] **Task 29: DockerSandbox — 隔离代码执行**
  - `src/acabot/sandbox/{base,docker_sandbox}.py`
  - 安全：无网络、只读文件系统、资源限制、超时保护

- [ ] **Task 30: CodeExecutionPlugin — 代码执行插件**
  - `src/acabot/plugins/code_execution/plugin.py`
  - 注册 `execute_code` tool 给 Agent

**v0.5 验收标准：**
- [ ] SQLiteKVStore 持久化 + update() 原子操作
- [ ] 分层压缩：tool 摘要 + 滚动摘要 + 简单截断回退
- [ ] NotepadPlugin 便签注入（用户级跨群 + 群级独立）
- [ ] SimpleMemPlugin 长期摘要（累积 → 摘要 → 门控检索）
- [ ] DockerSandbox 隔离执行（无网络、超时、输出截断）
- [ ] CodeExecutionPlugin 注册 tool 可用
