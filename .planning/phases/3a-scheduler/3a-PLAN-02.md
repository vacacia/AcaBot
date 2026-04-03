# Phase 3a Wave 2: Integration

**Requirements:** SCHED-07, SCHED-08

**前置依赖:** Wave 1 完成 (RuntimeScheduler, SQLiteScheduledTaskStore 可用)

## Overview

将 RuntimeScheduler 集成到现有 runtime 基础设施:
- 插件生命周期绑定: unload 时自动清理定时任务
- RuntimeApp 生命周期: start/stop 中正确启停 scheduler
- Bootstrap DI 组装: 创建并注入 scheduler 到各组件
- RuntimeComponents 扩展: 新增 scheduler 字段

---

## Task 1: 修改 RuntimePluginContext -- 添加 scheduler 字段

**文件:** `src/acabot/runtime/plugin_protocol.py`

**操作:** 修改

**变更:**

在 `RuntimePluginContext` dataclass 中新增可选字段:

```python
# 在现有 import 区域添加 TYPE_CHECKING 守卫导入
if TYPE_CHECKING:
    from acabot.runtime.scheduler import RuntimeScheduler

# 在 RuntimePluginContext dataclass 中添加字段 (放在末尾, 带默认值):
scheduler: RuntimeScheduler | None = None
```

注意: 使用 `TYPE_CHECKING` 守卫避免循环导入. `RuntimeScheduler` 的类型注解用字符串形式 (因为 `from __future__ import annotations` 已经在文件顶部).

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.plugin_protocol import RuntimePluginContext
import inspect
sig = inspect.signature(RuntimePluginContext)
assert 'scheduler' in sig.parameters, 'scheduler field missing'
print('RuntimePluginContext has scheduler field')
"
```

---

## Task 2: 修改 PluginRuntimeHost -- 注入 scheduler + unload 清理

**文件:** `src/acabot/runtime/plugin_runtime_host.py`

**操作:** 修改

**变更 2a: 构造函数新增 scheduler 参数**

在 `PluginRuntimeHost.__init__` 中:

```python
# 现有参数之后新增:
from __future__ import annotations  # 已经存在
# TYPE_CHECKING 区域添加:
if TYPE_CHECKING:
    from .scheduler import RuntimeScheduler

class PluginRuntimeHost:
    def __init__(
        self,
        tool_broker: ToolBroker,
        model_target_catalog: MutableModelTargetCatalog | None = None,
        scheduler: RuntimeScheduler | None = None,  # <-- 新增
    ) -> None:
        # ... 现有赋值 ...
        self._scheduler = scheduler  # <-- 新增
```

**变更 2b: unload_plugin 中添加定时任务清理**

在 `unload_plugin()` 方法中, 步骤 1 (注销工具) 之后、步骤 2 (注销 model targets) 之前, 添加:

```python
    # 1.5 注销定时任务
    if self._scheduler is not None:
        source_tag = self._plugin_tool_sources.get(plugin_id, f"plugin:{plugin_id}")
        cancelled_tasks = await self._scheduler.unregister_by_owner(source_tag)
        if cancelled_tasks:
            logger.info(
                "Plugin scheduled tasks cancelled: plugin=%s count=%d",
                plugin_id,
                len(cancelled_tasks),
            )
```

**变更 2c: _build_plugin_context 传递 scheduler**

找到构建 `RuntimePluginContext` 的位置 (在 `load_plugin` 方法中), 在构造 context 时传入 `scheduler=self._scheduler`.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.plugin_runtime_host import PluginRuntimeHost
import inspect
sig = inspect.signature(PluginRuntimeHost.__init__)
assert 'scheduler' in sig.parameters, 'scheduler param missing'
print('PluginRuntimeHost accepts scheduler')
"
```

---

## Task 3: 修改 RuntimeApp -- start/stop 生命周期集成

**文件:** `src/acabot/runtime/app.py`

**操作:** 修改

**变更 3a: 构造函数新增 scheduler 参数**

```python
# TYPE_CHECKING 或顶部 import 区域:
from __future__ import annotations  # 已存在

# 在构造函数参数列表中, long_term_memory_ingestor 之后添加:
    scheduler: RuntimeScheduler | None = None,  # 新增 (使用 TYPE_CHECKING 导入)

# 在 __init__ body 中:
    self.scheduler = scheduler
```

需要在 TYPE_CHECKING 块或正常 import 中添加:
```python
if TYPE_CHECKING:
    from .scheduler import RuntimeScheduler
```
如果已有 `TYPE_CHECKING` 块则追加, 否则新建. 注意: 由于 `from __future__ import annotations` 已存在, 类型注解中可以直接用 `RuntimeScheduler` 字符串形式.

**变更 3b: start() 方法**

在 `long_term_memory_ingestor.start()` 之后, `self.install()` 之前, 添加:

```python
    if self.scheduler is not None:
        await self.scheduler.start()
```

在异常处理 (except block) 中, `long_term_memory_ingestor.stop()` 之前, 添加 scheduler 的反向清理:

```python
    if self.scheduler is not None:
        try:
            await self.scheduler.stop()
        except Exception:
            logger.exception("Failed to stop scheduler after startup failure")
```

完整 start() 结构:
```python
async def start(self) -> None:
    await self.recover_active_runs()
    if self.plugin_reconciler is not None:
        await self.plugin_reconciler.reconcile_all()
    try:
        if self.long_term_memory_ingestor is not None:
            await self.long_term_memory_ingestor.start()
        if self.scheduler is not None:          # <-- 新增
            await self.scheduler.start()         # <-- 新增
        self.install()
        await self.gateway.start()
    except Exception:
        if self.scheduler is not None:           # <-- 新增
            try:                                  # <-- 新增
                await self.scheduler.stop()       # <-- 新增
            except Exception:                     # <-- 新增
                logger.exception("...")           # <-- 新增
        if self.long_term_memory_ingestor is not None:
            try:
                await self.long_term_memory_ingestor.stop()
            except Exception:
                logger.exception("...")
        if self.plugin_runtime_host is not None:
            try:
                await self.plugin_runtime_host.teardown_all()
            except Exception:
                logger.exception("...")
        raise
```

**变更 3c: stop() 方法**

在 `gateway.stop()` 之后, `plugin_runtime_host.teardown_all()` 之前, 添加 scheduler 停止:

```python
async def stop(self) -> None:
    stop_error: Exception | None = None
    try:
        await self.gateway.stop()
    except Exception as exc:
        stop_error = exc
    # Scheduler 在 plugin teardown 之前停止
    if self.scheduler is not None:               # <-- 新增
        try:                                      # <-- 新增
            await self.scheduler.stop()           # <-- 新增
        except Exception as exc:                  # <-- 新增
            logger.exception("Failed to stop scheduler during shutdown")
            if stop_error is None:                # <-- 新增
                stop_error = exc                  # <-- 新增
    if self.plugin_runtime_host is not None:
        # ... 原有逻辑 ...
```

理由: scheduler 在 plugin teardown 之前停止, 防止 teardown 期间还有定时任务触发.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.app import RuntimeApp
import inspect
sig = inspect.signature(RuntimeApp.__init__)
assert 'scheduler' in sig.parameters, 'scheduler param missing'
print('RuntimeApp accepts scheduler')
"
```

---

## Task 4: 修改 RuntimeComponents -- 添加 scheduler 字段

**文件:** `src/acabot/runtime/bootstrap/components.py`

**操作:** 修改

**变更:**

```python
# 顶部 import 区域添加:
from ..scheduler import RuntimeScheduler

# RuntimeComponents dataclass 中, long_term_memory_ingestor 附近添加:
    scheduler: RuntimeScheduler | None = None
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.bootstrap.components import RuntimeComponents
import dataclasses
field_names = [f.name for f in dataclasses.fields(RuntimeComponents)]
assert 'scheduler' in field_names, 'scheduler field missing'
print('RuntimeComponents has scheduler field')
"
```

---

## Task 5: 修改 build_runtime_components -- 创建并注入 scheduler

**文件:** `src/acabot/runtime/bootstrap/__init__.py`

**操作:** 修改

**变更 5a: 导入**

在文件顶部 import 区域添加:

```python
from ..scheduler import RuntimeScheduler, SQLiteScheduledTaskStore
```

**变更 5b: 在 `build_runtime_components()` 函数体中创建 scheduler**

在创建 `PluginRuntimeHost` 之前, 添加 scheduler 的构造. **必须复用现有的 `get_persistence_sqlite_path(config)` 辅助函数** (来自 `bootstrap/config.py`, 已在 `builders.py` 中导入), 并处理 `None` 返回值 (表示未配置持久化):

```python
    # 定时任务调度器
    from .config import get_persistence_sqlite_path
    scheduler_sqlite_path = get_persistence_sqlite_path(config)
    scheduler_store = SQLiteScheduledTaskStore(db_path=scheduler_sqlite_path) if scheduler_sqlite_path else None
    runtime_scheduler = RuntimeScheduler(store=scheduler_store)
```

注意: `get_persistence_sqlite_path(config)` 读取 `config.runtime.persistence.sqlite_path`, 返回解析后的绝对路径或 `None`. 当返回 `None` 时 (未配置持久化), scheduler 以纯内存模式运行 (`store=None`), persist=True 的任务注册会静默降级为不持久化.

**变更 5c: 注入到 PluginRuntimeHost**

找到 `PluginRuntimeHost(...)` 的构造调用, 添加 `scheduler=runtime_scheduler`:

```python
    runtime_plugin_host = PluginRuntimeHost(
        tool_broker=runtime_tool_broker,
        model_target_catalog=runtime_model_target_catalog,
        scheduler=runtime_scheduler,  # <-- 新增
    )
```

**变更 5d: 注入到 RuntimeApp**

找到 `RuntimeApp(...)` 的构造调用, 添加 `scheduler=runtime_scheduler`:

```python
    app = RuntimeApp(
        ...,
        scheduler=runtime_scheduler,  # <-- 新增
    )
```

**变更 5e: 注入到 RuntimePluginContext**

找到 `RuntimePluginContext(...)` 的构造, 添加 `scheduler=runtime_scheduler`. 这可能在 `PluginRuntimeHost._build_plugin_context` 中 (Task 2c 已处理), 或在 bootstrap 中直接构造. 确认实际构造位置.

**变更 5f: 注入到 RuntimeComponents**

在 `RuntimeComponents(...)` 构造中添加:

```python
    scheduler=runtime_scheduler,
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.bootstrap import build_runtime_components
print('bootstrap import OK')
"
```

---

## Task 6: 集成测试

**文件:** `tests/test_scheduler_integration.py`

**操作:** 新建

**测试用例:**

### 6.1 Plugin 生命周期绑定测试

- **`test_unload_plugin_cancels_scheduled_tasks`**:
  - 创建 RuntimeScheduler (store=None)
  - 创建 PluginRuntimeHost (传入 scheduler)
  - 构造一个简单的 FakePlugin, 在 setup() 中通过 ctx.scheduler 注册一个 interval 任务, owner 为 `"plugin:fake_test"`
  - 加载该插件
  - 验证 `scheduler.list_tasks()` 包含该任务
  - 卸载该插件
  - 验证 `scheduler.list_tasks()` 为空

- **`test_unload_plugin_without_scheduler_is_noop`**:
  - 创建 PluginRuntimeHost (scheduler=None)
  - 加载/卸载插件, 验证不 raise

### 6.2 RuntimeApp 生命周期测试

- **`test_app_start_starts_scheduler`**:
  - 创建 RuntimeScheduler (store=None)
  - 创建 RuntimeApp (传入 scheduler, 使用 FakeGateway 等 mock)
  - `await app.start()`
  - 验证 `scheduler._started is True`
  - `await app.stop()`
  - 验证 `scheduler._started is False`

- **`test_app_stop_order`**:
  - 创建 RuntimeScheduler, 包装 stop() 记录调用顺序
  - 创建 FakeGateway, 包装 stop() 记录调用顺序
  - 创建 RuntimeApp
  - `await app.start()`, `await app.stop()`
  - 验证调用顺序: gateway.stop -> scheduler.stop -> plugin_host.teardown

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_scheduler_integration.py -v
```

---

## Task 7: 更新 runtime/__init__.py 导出 (如 Wave 1 Task 7 未覆盖)

**文件:** `src/acabot/runtime/__init__.py`

**操作:** 修改 (如需要)

确认 `RuntimeScheduler` 已在 facade 导出中. 此 task 为 Wave 1 Task 7 的验证/补充.

---

## Execution Order

```
Task 1 (plugin_protocol.py)        -- 无 Wave 2 内部依赖
Task 2 (plugin_runtime_host.py)    -- 依赖 Task 1
Task 3 (app.py)                    -- 无 Wave 2 内部依赖
Task 4 (components.py)             -- 无 Wave 2 内部依赖
Task 5 (bootstrap/__init__.py)     -- 依赖 Task 1, 2, 3, 4
Task 6 (集成测试)                   -- 依赖 Task 1-5
Task 7 (runtime __init__)          -- 验证性, 随时可做
```

推荐顺序: Task 1 -> Task 4 -> Task 2 -> Task 3 -> Task 5 -> Task 7 -> Task 6

Task 1, 3, 4 可并行 (无互相依赖).

---

## Final Verification

全部 task 完成后执行:

```bash
# 1. 全量导入检查
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.scheduler import RuntimeScheduler
from acabot.runtime.plugin_protocol import RuntimePluginContext
from acabot.runtime.plugin_runtime_host import PluginRuntimeHost
from acabot.runtime.app import RuntimeApp
from acabot.runtime.bootstrap.components import RuntimeComponents
print('All imports OK')
"

# 2. 运行 Wave 1 + Wave 2 全部测试
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_scheduler.py tests/test_scheduler_integration.py -v

# 3. 确认现有测试不受影响
cd /data/workspace/agent/AcaBot && python -m pytest tests/ -v --timeout=30

# 4. Grep 确认 scheduler 已正确注入
cd /data/workspace/agent/AcaBot && grep -n "scheduler" src/acabot/runtime/app.py src/acabot/runtime/plugin_runtime_host.py src/acabot/runtime/bootstrap/__init__.py src/acabot/runtime/bootstrap/components.py
```

---

*Phase: 3a-scheduler, Wave 2*
*Requirements: SCHED-07, SCHED-08*
*Depends on: Wave 1 completed*
