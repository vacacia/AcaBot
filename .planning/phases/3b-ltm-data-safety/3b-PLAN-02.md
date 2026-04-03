# Phase 3b Wave 2: LTM 周期性备份

**Phase:** 3b-ltm-data-safety
**Wave:** 2 of 2
**Scope:** LTM-02 (periodic backup capability)
**Depends on:** Wave 1 (threading.Lock 已就位) + Phase 3a (RuntimeScheduler 已可用)
**Estimated tasks:** 4

---

## 前置条件

- Wave 1 完成: `LanceDbLongTermMemoryStore._write_lock` (threading.Lock) 已存在
- Phase 3a 完成: `RuntimeScheduler` 已集成到 `RuntimeApp` (app.py L75, L134-135)
- `RuntimeScheduler.register()` async 接口可用 (scheduler/scheduler.py L153)

---

## 执行顺序

```
Task 1 — LanceDbLongTermMemoryStore.backup() + _cleanup_old_backups()
Task 2 — 备份配置解析 + bootstrap/app 注册定时任务
Task 3 — 备份单元测试
Task 4 — 备份集成测试 (SC-2: 可恢复快照)
```

---

## Task 1: backup() 方法

**需求:** LTM-02
**文件:** `src/acabot/runtime/memory/long_term_memory/storage.py`

### 改动

在 `LanceDbLongTermMemoryStore` 类中新增两个方法 (放在 `validate()` 之后):

```python
def backup(self, target_dir: str | Path, *, max_backups: int = 5) -> Path:
    """创建 LanceDB 数据目录的一致性备份.

    备份期间持有写锁, 确保不会拷到写入中间状态.
    备份目录命名: lancedb-backup-{YYYYMMDD-HHMMSS}.
    超过 max_backups 份时自动删除最旧的备份.

    Args:
        target_dir: 备份目标父目录.
        max_backups: 最多保留的备份份数, 0 表示不限制.

    Returns:
        本次备份的完整路径.
    """

    import shutil
    import time as _time

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    timestamp = _time.strftime("%Y%m%d-%H%M%S")
    backup_path = target / f"lancedb-backup-{timestamp}"

    with self._write_lock:
        shutil.copytree(str(self.root_dir), str(backup_path))

    logger.info("LTM 备份完成: %s", backup_path)

    if max_backups > 0:
        self._cleanup_old_backups(target, max_backups=max_backups)

    return backup_path

@staticmethod
def _cleanup_old_backups(target_dir: Path, *, max_backups: int) -> None:
    """清理旧备份, 只保留最近 max_backups 份.

    Args:
        target_dir: 备份目录.
        max_backups: 最多保留份数.
    """

    import shutil

    prefix = "lancedb-backup-"
    backups = sorted(
        [d for d in target_dir.iterdir() if d.is_dir() and d.name.startswith(prefix)],
        key=lambda d: d.name,
        reverse=True,
    )
    for old_backup in backups[max_backups:]:
        shutil.rmtree(old_backup, ignore_errors=True)
        logger.info("已清理旧 LTM 备份: %s", old_backup.name)
```

### 设计决策

- 备份在 `with self._write_lock:` 内执行 copytree, 保证一致性 (D-02)
- 使用本地时间戳命名, 排序即时间顺序
- 清理在锁外执行, 不阻塞写入
- backup() 是同步方法, 调度器通过 `asyncio.to_thread()` 调用

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
from pathlib import Path
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
store = LanceDbLongTermMemoryStore('/tmp/test_ltm_backup_src')
backup_path = store.backup('/tmp/test_ltm_backup_dst')
assert backup_path.exists()
assert backup_path.name.startswith('lancedb-backup-')
print(f'OK: backup at {backup_path}')
"
```

---

## Task 2: 备份配置 + 定时任务注册

**需求:** LTM-02
**文件:** `src/acabot/runtime/bootstrap/builders.py`, `src/acabot/runtime/app.py`, `src/acabot/runtime/bootstrap/__init__.py`

### 配置格式

在 `config.example.yaml` 的 `runtime.long_term_memory` 下添加:

```yaml
runtime:
  long_term_memory:
    enabled: false
    # backup:
    #   enabled: true              # 是否启用定时备份
    #   interval_hours: 24         # 备份间隔 (小时), 默认 24
    #   max_backups: 5             # 最多保留份数, 默认 5
    #   backup_dir: "long_term_memory/backups"  # 相对于 runtime_data/
```

### 改动 2a: builders.py

新增 `build_ltm_backup_task()` 函数:

```python
def build_ltm_backup_task(
    config: Config,
    *,
    store: LanceDbLongTermMemoryStore,
) -> tuple[Callable[[], Awaitable[None]], int] | None:
    """构造 LTM 备份回调和调度间隔.

    Args:
        config: 当前 runtime 配置.
        store: LTM 存储实例.

    Returns:
        (async_callback, interval_seconds) 元组; 备份未启用时返回 None.
    """

    import asyncio as _asyncio

    long_term_memory_conf = _long_term_memory_config(config)
    backup_conf = dict(long_term_memory_conf.get("backup", {}))
    if not bool(backup_conf.get("enabled", False)):
        return None

    interval_hours = int(backup_conf.get("interval_hours", 24) or 24)
    max_backups = int(backup_conf.get("max_backups", 5) or 5)
    backup_dir = resolve_runtime_path(
        config,
        backup_conf.get("backup_dir", "long_term_memory/backups"),
    )

    async def _backup_callback() -> None:
        await _asyncio.to_thread(store.backup, backup_dir, max_backups=max_backups)

    return _backup_callback, interval_hours * 3600
```

### 改动 2b: app.py — RuntimeApp 接受 ltm_store + config

**问题:** `build_runtime_components()` 是同步函数, 但 `scheduler.register()` 是 async.
备份任务需要在 `RuntimeApp.start()` 中注册.

在 `RuntimeApp.__init__()` 中新增可选参数:
```python
def __init__(
    self,
    *,
    # ... 现有参数 ...
    ltm_store=None,        # LanceDbLongTermMemoryStore | None
    config: Config | None = None,
):
    # ... 现有赋值 ...
    self._ltm_store = ltm_store
    self._config = config
```

在 `RuntimeApp.start()` 中, scheduler 启动之前注册备份任务:
```python
async def start(self) -> None:
    # ... 现有 ingestor 启动逻辑 (Wave 1 Task 4 已修改) ...

    # LTM 定时备份注册
    if (
        self.scheduler is not None
        and self._ltm_store is not None
        and self._config is not None
    ):
        try:
            from .bootstrap.builders import build_ltm_backup_task
            from .scheduler.contracts import IntervalSchedule
            ltm_backup_task = build_ltm_backup_task(self._config, store=self._ltm_store)
            if ltm_backup_task is not None:
                callback, interval = ltm_backup_task
                await self.scheduler.register(
                    task_id="ltm_backup",
                    owner="runtime.ltm",
                    schedule=IntervalSchedule(seconds=interval),
                    callback=callback,
                    persist=False,
                    misfire_policy="skip",
                    metadata={"description": "LTM 定期备份"},
                )
                logger.info("LTM 定期备份任务已注册, 间隔 %d 秒", interval)
        except Exception:
            logger.exception("LTM 备份任务注册失败, 跳过定期备份")

    try:
        if self.scheduler is not None:
            await self.scheduler.start()
        # ...
```

### 改动 2c: bootstrap/__init__.py — 传递 ltm_store 和 config

在 `RuntimeApp(...)` 构造处 (~L448) 添加参数:

```python
app = RuntimeApp(
    # ... 现有参数 ...
    ltm_store=runtime_long_term_memory_store,
    config=config,
)
```

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.bootstrap.builders import build_ltm_backup_task
print('OK: build_ltm_backup_task importable')
"
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.app import RuntimeApp
print('OK: app imports clean')
"
```

---

## Task 3: 备份单元测试

**需求:** LTM-02 验证
**文件:** `tests/runtime/test_ltm_backup.py` (新建)

### 测试用例

1. **test_backup_creates_directory_copy** — `backup()` 创建目录, 名称以 `lancedb-backup-` 开头, 包含 LanceDB 文件
2. **test_backup_contains_entries_data** — 先写入 entries, 备份后目录非空
3. **test_backup_cleanup_old** — 连续 7 次 backup(max_backups=5), 验证只保留最新 5 份
4. **test_backup_empty_store** — 空 store 备份成功, 不报错
5. **test_backup_holds_write_lock_during_copy** — mock `shutil.copytree` 验证在锁内调用 (或用 threading.Event 协调验证并发 upsert 在 backup 期间被阻塞)

### 测试策略

- 使用 `tmp_path` fixture 创建临时目录
- 每个测试构造独立的 `LanceDbLongTermMemoryStore` 实例
- 对 max_backups 测试: 用 `time.sleep(1)` 或 mock time 确保不同备份有不同时间戳

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_backup.py -v
```

---

## Task 4: 备份集成测试 (SC-2)

**需求:** SC-2 验证
**文件:** `tests/runtime/test_ltm_data_safety.py` (追加到 Wave 1 Task 7 创建的文件)

### 新增测试用例

```python
def test_backup_produces_restorable_snapshot(tmp_path):
    """SC-2: 备份产生可恢复快照.

    流程:
    1. 创建 store, 写入 entries + cursors
    2. 执行 backup()
    3. 用备份目录创建新 LanceDbLongTermMemoryStore
    4. 新 store 能读回所有原始数据
    5. 新 store validate() 通过
    """

    src_dir = tmp_path / "lancedb"
    backup_dir = tmp_path / "backups"

    store = LanceDbLongTermMemoryStore(src_dir)
    store.upsert_entries([make_entry("e-1"), make_entry("e-2"), make_entry("e-3")])
    store.save_cursor(ThreadLtmCursor(
        thread_id="t-1", last_event_id=100, last_message_id=50, updated_at=1000,
    ))

    backup_path = store.backup(backup_dir)

    # 从备份恢复
    restored = LanceDbLongTermMemoryStore(backup_path)
    validation = restored.validate()
    assert validation.ok, f"Restore validation failed: {validation.errors}"

    # 验证 entries
    for eid in ["e-1", "e-2", "e-3"]:
        assert restored.get_entry(eid) is not None, f"entry {eid} missing from backup"

    # 验证 cursor
    cursor = restored.load_cursor("t-1")
    assert cursor is not None
    assert cursor.last_event_id == 100
```

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_data_safety.py -v -k "backup"
```

---

## 全量回归验证

完成所有 4 个 Task 后:

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/ -v --timeout=60
```

重点确认:
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_backup.py tests/runtime/test_ltm_data_safety.py tests/runtime/test_ltm_write_lock.py tests/runtime/test_long_term_memory_storage.py -v
```

---

## 文件变更汇总

| 文件 | 操作 | Task |
|------|------|------|
| `src/acabot/runtime/memory/long_term_memory/storage.py` | 修改 (新增 backup + _cleanup_old_backups) | 1 |
| `src/acabot/runtime/bootstrap/builders.py` | 修改 (新增 build_ltm_backup_task) | 2 |
| `src/acabot/runtime/bootstrap/__init__.py` | 修改 (传递 ltm_store + config 给 RuntimeApp) | 2 |
| `src/acabot/runtime/app.py` | 修改 (新增 ltm_store/config 参数 + start 中注册备份任务) | 2 |
| `config.example.yaml` | 修改 (添加 backup 配置注释) | 2 |
| `tests/runtime/test_ltm_backup.py` | 新建 | 3 |
| `tests/runtime/test_ltm_data_safety.py` | 追加 | 4 |

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `shutil.copytree()` 在大数据量下耗时长, 持锁阻塞写入 | LTM 数据量当前小 (<100MB); 备份间隔长 (默认每日); 写入频率低 |
| 备份目录磁盘膨胀 | `_cleanup_old_backups` 自动清理, 默认只保留 5 份 |
| `build_runtime_components` 同步 vs scheduler.register 异步 | 注册推迟到 `RuntimeApp.start()` 中执行 |
| 备份期间进程崩溃导致不完整 copytree | 不完整目录名可通过时间戳识别; 恢复前应先 validate() |
| 同一秒内两次备份导致目录名冲突 | 默认间隔 24h, 冲突概率极低; 必要时可改用 microsecond 精度 |

## 前置条件检查清单

- [ ] Wave 1 完成 — `LanceDbLongTermMemoryStore._write_lock` 可用
- [ ] Wave 1 完成 — `LanceDbLongTermMemoryStore.validate()` 可用
- [ ] Phase 3a 完成 — `RuntimeScheduler.register()` API 稳定
- [ ] Phase 3a 完成 — `IntervalSchedule` 数据类可用

## Success Criteria 覆盖

| SC | 描述 | Task |
|----|------|------|
| SC-2 | 定期备份产生可恢复快照, 在配置的备份目录中 | Task 1 (backup) + Task 2 (定时注册) + Task 4 (集成测试) |
