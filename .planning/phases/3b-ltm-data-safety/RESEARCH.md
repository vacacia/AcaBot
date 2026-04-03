# Phase 3b: LTM Data Safety -- Research

## 概述

本文档记录了 LTM (Long-Term Memory) 数据安全相关的代码调研结果,
覆盖写序列化、备份、启动校验、优雅降级四个需求.

---

## LTM-01: asyncio.Lock 写序列化

### 现状分析

**当前没有任何写锁保护.** 所有 LanceDB 写操作都通过 `asyncio.to_thread()` 调用同步方法,
多个并发 `to_thread()` 可能同时进入 `LanceDbLongTermMemoryStore` 的写方法, 导致竞态.

### 需要加锁的写操作

以下方法都执行了 "读全表 -> 修改 -> 整表重写" 的模式, 是典型的 read-modify-write 竞态:

| 方法 | 文件 | 行号 | 说明 |
|------|------|------|------|
| `upsert_entries()` | `storage.py` | L419-448 | 主表整表重写, 最关键的写路径 |
| `save_cursor()` | `storage.py` | L597-614 | cursor 表整表重写 |
| `save_failed_window()` | `storage.py` | L636-653 | failed_windows 表整表重写 |
| `delete_entry()` | `storage.py` | L790-806 | 主表删除后重写 |
| `delete_entries_by_conversation()` | `storage.py` | L808-824 | 主表按 conversation 删除后重写 |
| `update_entry()` | `storage.py` | L826-876 | 主表单条更新后重写 |

### 调用方分析

写操作的调用链路:

1. **Ingestor 写入链路** (最频繁):
   - `LongTermMemoryIngestor._process_thread()` (L262-301, `long_term_ingestor.py`)
   - -> `LtmWritePort.ingest_thread_delta()` (L107-172, `write_port.py`)
   - -> `asyncio.to_thread(self.store.upsert_entries, ...)` (L140, `write_port.py`)
   - -> `asyncio.to_thread(self.store.save_cursor, ...)` 间接通过 `save_cursor()` (L103-105)
   - -> `asyncio.to_thread(self.store.save_failed_window, ...)` (L164, `write_port.py`)

2. **WebUI / Control Plane 写入** (偶发):
   - `delete_entry()`, `delete_entries_by_conversation()`, `update_entry()` 通过 HTTP API 调用

### 推荐方案

在 `LtmWritePort` 层加一把 `asyncio.Lock`, 而不是在 `LanceDbLongTermMemoryStore` 层.
原因:
- `LanceDbLongTermMemoryStore` 是同步类, 在里面放 asyncio.Lock 不自然
- `LtmWritePort` 是唯一的 async 写入入口, 由 Ingestor 调用
- WebUI 的 delete/update 操作需要单独在调用侧加锁, 或者抽出一个统一的 async wrapper

**具体做法**: 在 `LtmWritePort.__init__()` 中新增 `self._write_lock = asyncio.Lock()`,
在 `ingest_thread_delta()` 的每个 `asyncio.to_thread()` 调用处使用 `async with self._write_lock`.
对于 WebUI 侧的写操作, 建议在 `LanceDbLongTermMemoryStore` 外包一层 `LockedLtmStoreProxy`
或在 ControlPlane 调用处统一获取同一把锁.

**更简洁方案**: 在 `LanceDbLongTermMemoryStore` 上增加一个 `threading.Lock`,
因为所有写操作最终都在 `to_thread()` 的线程池中执行, `threading.Lock` 是正确的同步原语.
这样无论从 Ingestor 还是 WebUI 调用, 都能保证写序列化.

### 风险

- LanceDB 整表重写策略本身性能不高, 加锁会进一步串行化写入; 但当前写入量很低, 可接受
- `threading.Lock` 在 `to_thread()` 中可能导致线程池线程被阻塞; 但写操作频率很低, 影响有限

---

## LTM-02: 周期性备份

### 当前 LanceDB 存储路径

配置路径: `runtime.long_term_memory.storage_dir`, 默认值 `long_term_memory/lancedb`
(相对于 `runtime_data/` 目录).

构造位置: `builders.py` L185-208, `build_long_term_memory_store()` 函数.
`LanceDbLongTermMemoryStore.__init__()` 中 `self.root_dir = Path(root_dir)` (storage.py L411).

LanceDB 数据目录结构: 由 LanceDB 库管理, 包含 `.lance` 文件和元数据.
备份可以简单地对 `root_dir` 做目录级 copy.

### 调度器接入点

Phase 3a 完成的 `RuntimeScheduler` 支持 cron / interval / one-shot 三种调度类型.
已经集成到 `RuntimeApp` 中 (app.py L75, L134-135).

`RuntimeScheduler` 通过 `register_task()` 注册回调, 接受 `IntervalSchedule` 或 `CronSchedule`.

### 推荐方案

1. 在 `LanceDbLongTermMemoryStore` 上新增 `backup(target_dir: Path) -> Path` 同步方法:
   - 使用 `shutil.copytree()` 把 `self.root_dir` 复制到 `target_dir / lancedb-backup-{timestamp}`
   - 返回备份目录路径
   - 可选: 保留最近 N 份备份, 删除更旧的

2. 在 bootstrap 阶段注册定时备份任务:
   - 位置: `build_runtime_components()` 中构造 `RuntimeScheduler` 之后 (bootstrap/__init__.py ~L332)
   - 使用 `IntervalSchedule(seconds=86400)` (每日一次) 或从配置读取
   - 回调: `asyncio.to_thread(store.backup, backup_dir)`

3. 备份目标路径: `runtime_data/long_term_memory/backups/`

### 风险

- `shutil.copytree()` 在 LanceDB 正在写入时可能拷到不一致状态
  - 缓解: 配合 LTM-01 的写锁, 备份时先获取锁, 保证没有并发写入
- 备份目录可能膨胀; 需要清理策略 (保留最近 N 份)

---

## LTM-03: 启动完整性校验

### 当前启动流程

1. `build_long_term_memory_store(config)` (builders.py L185-208):
   - 导入 `LanceDbLongTermMemoryStore`
   - 调用 `LanceDbLongTermMemoryStore(storage_dir)`
2. `LanceDbLongTermMemoryStore.__init__()` (storage.py L404-417):
   - `self.root_dir.mkdir(parents=True, exist_ok=True)`
   - `self._db = lancedb.connect(str(self.root_dir))`
   - `self._entries = self._ensure_table("memory_entries", ...)` -- 用 `exist_ok=True` 创建/打开表
   - `self._entries.create_fts_index("lexical_text", replace=True)` -- 重建 FTS 索引
   - 同样处理 `thread_cursors` 和 `failed_windows` 表

3. 该 store 在 bootstrap 的 `build_runtime_components()` 中被构造 (bootstrap/__init__.py L191-194).
4. 之后 `RuntimeApp.start()` 启动 ingestor: `await self.long_term_memory_ingestor.start()` (app.py L132-133).

### 当前缺失的校验

- 没有检查已有表的 schema 是否与代码期望一致
- 没有检查 LanceDB 目录内文件是否损坏
- `lancedb.connect()` + `_ensure_table()` 如果遇到损坏数据, 会直接抛异常, 阻塞整个启动

### 推荐方案

1. 在 `LanceDbLongTermMemoryStore` 中新增 `validate() -> LtmValidationResult` 方法:
   - 尝试 `to_arrow()` 每个表, 确认可以读取
   - 检查表的 column names 是否包含期望字段
   - 返回结构化的校验结果 (ok / warnings / errors)

2. 在 `build_long_term_memory_store()` 之后调用 `validate()`:
   - 校验通过: 正常继续
   - 校验失败但可恢复: 日志告警, 尝试从最近备份恢复 (如果 LTM-02 已实现)
   - 校验失败且不可恢复: 日志错误, 将 `long_term_memory_enabled` 置为 False, 进入降级模式

3. 插入位置: `build_runtime_components()` 中, L191 `build_long_term_memory_store()` 之后,
   在 `build_long_term_memory_source()` 和 `build_long_term_memory_write_port()` 之前.

### 风险

- schema 迁移: 当代码更新导致 schema 变更时, 校验会报错; 需要考虑 schema 版本管理或宽松匹配
- LanceDB 内部元数据损坏可能导致 `lancedb.connect()` 本身就失败, 需要在更外层 catch

---

## LTM-04: 优雅降级

### 现有降级模式

1. **MemoryBroker 层** (memory_broker.py L162-173):
   - 每个 `MemorySource.__call__()` 在 try/except 中执行
   - source 抛异常时记录 `MemorySourceFailure`, 跳过继续
   - **这是现成的降级点**, LTM source 出错不会阻塞 pipeline

2. **Ingestor 层** (long_term_ingestor.py L248-255):
   - `_worker_loop` 中 `_process_thread()` 抛异常时 `logger.exception()` 并继续循环
   - **写入侧已经有基本的容错**

3. **Write Port 层** (write_port.py L141-168):
   - 单窗口失败时记录 `FailedWindowRecord`, 继续处理后续窗口
   - 失败记录本身写不进去时返回 `advance_cursor=False`
   - **窗口级别的容错已经完备**

4. **App 启动层** (app.py L132-154):
   - `long_term_memory_ingestor.start()` 如果失败, 会触发全局 startup rollback
   - **这里缺乏降级**: LTM 启动失败不应阻塞整个 runtime

### 缺失的降级点

| 位置 | 问题 | 建议 |
|------|------|------|
| `build_long_term_memory_store()` (builders.py L185-208) | `LanceDbLongTermMemoryStore()` 构造失败会终止启动 | 用 try/except 包裹, 失败时 log + 返回 None |
| `build_runtime_components()` (bootstrap/__init__.py L190-218) | LTM 相关组件构造失败会终止启动 | 失败时跳过 LTM 组件, 让 memory_broker 不注册 ltm source |
| `RuntimeApp.start()` (app.py L132-133) | `ingestor.start()` 失败触发全局 rollback | 改为 try/except + log warning, 不阻塞启动 |
| `LtmMemorySource.__call__()` (source.py L151-205) | 检索侧的 LLM 调用或 store 操作可能失败 | **已有降级** -- MemoryBroker 会 catch |

### 推荐方案

1. **启动降级**: 在 `build_runtime_components()` 中, 用 try/except 包裹整个 LTM 构造块:
   ```python
   try:
       runtime_long_term_memory_store = build_long_term_memory_store(config)
       # ... validate + build source + build write port + build ingestor
   except Exception:
       logger.exception("LTM initialization failed, running without long-term memory")
       runtime_long_term_memory_store = None
       runtime_long_term_memory_source = None
       runtime_long_term_memory_ingestor = None
   ```

2. **运行时降级**: 在 `RuntimeApp.start()` 中, ingestor 启动失败时不 rollback:
   ```python
   if self.long_term_memory_ingestor is not None:
       try:
           await self.long_term_memory_ingestor.start()
       except Exception:
           logger.exception("LTM ingestor start failed, continuing without LTM writes")
           self.long_term_memory_ingestor = None
   ```

3. **LtmMemorySource 自身降级**: 虽然 MemoryBroker 已经 catch 了 source 异常,
   建议在 `LtmMemorySource.__call__()` 内部也加 try/except, 返回空列表并记录日志,
   提供更精确的错误信息 (区分 query_planner 失败 vs store 失败).

---

## 关键集成点汇总

| 需求 | 主要修改文件 | 行号/方法 |
|------|-------------|----------|
| LTM-01 写锁 | `storage.py` | 在类上增加 `threading.Lock`, 所有写方法入口获取 |
| LTM-01 写锁 | `write_port.py` | 如果选择 asyncio.Lock 方案则在此加锁 |
| LTM-02 备份 | `storage.py` | 新增 `backup()` 方法 |
| LTM-02 备份 | `bootstrap/__init__.py` ~L332 | 注册定时备份任务到 RuntimeScheduler |
| LTM-02 备份 | `builders.py` | 新增 `build_ltm_backup_task()` 辅助函数 |
| LTM-03 校验 | `storage.py` | 新增 `validate()` 方法 |
| LTM-03 校验 | `builders.py` L185-208 | `build_long_term_memory_store()` 后调用 validate |
| LTM-04 降级 | `bootstrap/__init__.py` L190-218 | try/except 包裹 LTM 构造块 |
| LTM-04 降级 | `app.py` L132-133 | ingestor.start() 失败不 rollback |

## 依赖关系

- LTM-01 (写锁) 独立, 可先做
- LTM-02 (备份) 依赖 LTM-01 (备份时获取写锁保证一致性)
- LTM-03 (校验) 独立, 可与 LTM-01 并行
- LTM-04 (降级) 独立, 但如果 LTM-03 先完成, 降级逻辑可以更精细

推荐实施顺序: LTM-01 -> LTM-04 -> LTM-03 -> LTM-02

## 补充发现

1. **整表重写策略**: `LanceDbLongTermMemoryStore` 当前所有写操作都是 "读全表 -> 合并 -> 重写" 模式
   (`_rewrite_table` / `_rewrite_entries_table`). 这在数据量增大后会成为性能瓶颈,
   但不属于本 phase 范围. 加写锁后至少能保证正确性.

2. **FTS 索引重建**: 每次 `_rewrite_entries_table()` 都会 `create_fts_index("lexical_text", replace=True)`,
   这是一个重操作. 在备份时如果发生重建, 可能影响备份一致性. 需要确保写锁覆盖整个操作.

3. **Ingestor 单 worker 模型**: `LongTermMemoryIngestor` 只有一个 worker loop (L239-260),
   逐个处理 dirty threads, 不会并发处理多个 thread. 这意味着从 Ingestor 侧来的写操作
   天然是串行的. 竞态主要来自 Ingestor 和 WebUI 的并发. `threading.Lock` 方案最简洁.

4. **WebUI delete/update 调用路径**: 这些操作在 `RuntimeControlPlane` -> `LanceDbLongTermMemoryStore`
   之间直接调用, 没有经过 `LtmWritePort`. 如果只在 `LtmWritePort` 加 asyncio.Lock,
   无法保护 WebUI 侧的写操作. 因此 **推荐在 `LanceDbLongTermMemoryStore` 层加 `threading.Lock`**.
