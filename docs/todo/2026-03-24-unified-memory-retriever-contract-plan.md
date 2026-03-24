# 2026-03-24 统一长期记忆 Source Registry 与 Retrieval Contract 小计划

这份小计划只讲设计方向，不展开到具体代码实现步骤。

它建立在下面这份设计之上：

- `docs/todo/2026-03-23-unified-context-contribution-and-assembly-design.md`

这次要解决的核心不是“再定义一种记忆分类”，而是把“长期记忆如何接入 runtime 主线”收成稳定边界。

---

## 目标

希望系统满足下面这个性质：

- 不管以后新增的是 `/self`
- sticky note
- store-backed 长期记忆
- relationship / channel memory
- 外部 RAG
- 其他插件侧 memory source

它们都通过同一套 retrieval contract 接入 runtime。

换句话说：

> 新增长期记忆时，主要工作应该是“注册一个新的 memory source”，而不是“继续修改 runtime 主线里谁去查谁的枚举列表”。

---

## 开头先记下这次收出来的结论

### 1. `requested_memory_types` 不是正式主线

`requested_memory_types` 这层抽象目前没有带来足够价值。

它的问题是：

- 语义不稳定
- 很容易变成拍脑袋分类
- 对 source 调度帮助不大

所以这一层不应该继续作为正式 contract 保留。

### 2. `requested_sources` 也不该成为设计中心

`requested_sources` 看起来比 `memory_type` 更接近真实系统，但它仍然有一个问题：

- 每新增一个 source，都要继续维护一份“该调谁”的列表

这会让 planner 或 WebUI 逐渐变成新的 source 枚举中心。

所以 `requested_sources` 最多只能是 broker 这一轮的临时执行视图，不应该成为长期正式设计中心。

### 3. 真正的中心应该是 `MemorySourceRegistry`

系统应该维护一份正式的 source registry：

- 内置 source 在 bootstrap 注册
- 外部 source 在 plugin / runtime 扩展阶段注册

后面主线不再依赖“某个列表里写了谁”，而是依赖“registry 里当前有哪些可用 source”。

### 4. source 自己声明装配意图

如果一个 source 连自己想插到哪里、优先级大概是多少都不能表达，最后 assembler 就只能靠猜。

所以正式设计里：

- source 自己声明 `target_slot`
- source 自己声明 `priority`

assembler 不再推断来源意图，只做校验、排序、裁剪和落地。

### 5. 装配声明可以进入 retrieval 输出，但要隔离表达

`MemoryBlock` 可以携带装配声明，但不要把 retrieval 核心字段和 assembly 字段揉成一团。

更好的方式是：

- `MemoryBlock`
  - 负责表达 source 产出的内容
- `MemoryAssemblySpec`
  - 负责表达这块内容希望如何被组装

这样 retrieval contract 和 assembly contract 虽然连着，但边界仍然清楚。

---

## 核心原则

### 1. 统一的是 source contract，不是记忆分类

系统里真正应该统一的是：

- source 的注册方式
- source 的调用 contract
- source 的输出对象

而不是强行给所有内容定义一个统一 `memory_type` 分类体系。

### 2. `RetrievalPlanner` 负责准备共享检索上下文，不负责路由表

`RetrievalPlanner` 后面应该负责：

- 产出 `query_text`
- 产出 `requested_tags`
- 产出 `working_summary`
- 产出 `retained_history`
- 产出其他共享 retrieval metadata

它不再负责维护“这轮要点名调用哪些 source”的中心列表。

### 3. source 自己决定这轮要不要产出内容

每个 source 都收到同一份共享 retrieval request。

然后 source 自己判断：

- 这轮要不要工作
- 如果工作，要返回哪些 `MemoryBlock`
- 这些 block 应该插到哪里
- 这些 block 的优先级是多少

### 4. broker 只做调度、合并和失败汇总

`MemoryBroker` 不负责：

- 猜测来源意图
- 全局排序
- token trim

它只负责：

- 迭代已注册且当前启用的 source
- 调用它们
- 合并成功结果
- 记录失败结果

### 5. assembler 不关心来源怎么检索，只关心来源交上来的内容块和装配声明

更准确的措辞应该是：

> `ContextAssembler` 不关心来源如何检索、存储或命中，只消费来源已经产出的内容块及其装配声明，并在全局约束下完成校验、排序、裁剪和最终 payload 生成。

---

## 建议收硬的稳定边界

## 1. `MemorySourceRegistry`

registry 是正式中心。

它负责：

- 保存当前有哪些 source
- 暴露 source 的可枚举列表
- 支持注册 / 注销 / 查询

它表达的是：

> 当前 runtime 里，哪些长期记忆来源是“可以被调用”的。

内置 source 的例子：

- `self`
- `sticky_notes`
- `store_memory`

外部 source 的例子：

- `external_rag:project_docs`
- `external_rag:workspace_notes`
- `reference_backend:openviking`

---

## 2. `MemorySourcePolicy`

如果后面要让 WebUI 控制 source，不应该去编辑 `requested_sources` 列表，而应该控制 source policy。

这层适合表达：

- source 是否启用
- source 是否只在某些 session / profile 启用
- source 是否允许写某些 `target_slot`
- source 的默认排序护栏

也就是说，WebUI 未来适合做成：

- 查看当前 registry 里有哪些 source
- 配置每个 source 的启用状态和权限

而不是维护一份“这轮调谁”的枚举列表。

---

## 3. `SharedMemoryRetrievalRequest`

planner 最终应该产出一份共享检索请求，而不是 source 名单。

它可以理解成：

```text
RunContext
  -> RetrievalPlanner.prepare_shared_request()
  -> SharedMemoryRetrievalRequest
```

这份共享 request 里，下面这些应该是一等字段，而不是继续塞进 `metadata`：

- `run_id`
- `thread_id`
- `actor_id`
- `agent_id`
- `channel_scope`
- `event_id`
- `event_type`
- `event_timestamp`
- `event_tags`
- `query_text`
- `requested_tags`
- `working_summary`
- `retained_history`

原因很简单：

- 这些字段稳定
- 多个 source 都可能直接依赖
- 它们属于 retrieval 主线的正式输入，不是附加信息

只有下面这些才应该继续放进 `metadata`：

- 某个 source 才会用到的私有扩展字段
- 实验性 retrieval 参数
- 调试辅助信息
- 暂时还不确定是否应该升格的一次性字段

所有 source 都收到这一份 request。

至于这轮到底谁真正返回内容，不由 planner 硬编码决定，而由 source 自己判断。

---

## 4. `MemoryBlock`

`MemoryBlock` 是 source 产出的统一内容块。

建议它只表达：

- `content`
- `source`
- `scope`
- `source_ids`
- `assembly`
- `metadata`

字段语义如下：

- `content`
  - 真正给模型看的正文
- `source`
  - 哪个 source 产出的这块内容
- `scope`
  - 这块内容挂在哪个作用域上，例如 `global` / `user` / `channel`
- `source_ids`
  - 指向原始来源记录，方便 trace / UI / 调试
- `assembly`
  - 这块内容附带的装配声明
- `metadata`
  - score、uri、doc_id、更新时间等补充信息

这里故意不把 `target_slot` 和 `priority` 裸放在顶层，是为了避免 retrieval 核心字段和 assembly 字段混在一起。

---

## 5. `MemoryAssemblySpec`

装配声明从 `MemoryBlock` 里独立出来。

建议最小表达：

- `target_slot`
- `priority`

也就是说：

- source 自己声明这块内容应该插到哪里
- source 自己声明这块内容的排序优先级

而不是把意图留给 assembler 猜。

推荐语义是：

- `target_slot`
  - 例如 `message_prefix`
- `priority`
  - 一个可比较的排序值

如果以后要加更多 assembly 信息，再继续往 `MemoryAssemblySpec` 扩，而不是污染 `MemoryBlock` 顶层。

---

## 6. `MemoryBrokerResult`

broker 不应该只返回一组成功内容，而应该显式表达 merge 和 failure 结果。

建议 broker 的 retrieval 结果至少包含：

- `blocks`
- `failures`

也可以视需要再保留：

- `attempted_sources`
- `skipped_sources`

它表达的是：

- 哪些 source 真正产出了内容
- 哪些 source 失败了
- 哪些 source 被跳过了

这样 WebUI、trace、payload 调试面都能拿到完整信息，而不是只有一堆成功 block。

---

## Broker 的 merge / failure 语义

这一层需要明确，不然后面 source 多起来就会乱。

> 某个 memory source 如果失败了，系统到底应该多认真对待
required 表示：这个 source 本轮应该被执行，而且它不应该被静默跳过; 如果被禁用、没注册、被过滤掉、或者直接没跑，不能当没事发生, 至少要留下明确 failure / warning / trace

fatal 表示：这个 source 一旦失败，整轮 retrieval / 甚至整轮 run 都不能继续按正常路径走

### merge 语义

- broker 按 registry + policy 计算本轮启用 source
- 按固定顺序调用 source
- 每个 source 返回自己的 `list[MemoryBlock]`
- broker 保留 source 内部返回顺序
- broker 合并成功结果，但不做全局排序

也就是说：

> broker 的 merge 是“收集并串联”，不是“理解并重排”。

### failure 语义

- 单个 source 失败，默认不打断整轮 retrieval
- 失败必须记录到 `failures`
- 其他 source 继续执行
- assembler 只消费成功的 `blocks`

也就是说：

> broker 默认走 best-effort retrieval，但失败不能 silent swallow。

如果以后真的需要“某个 source 必须成功”，那再在 policy 层补 required / fatal 语义，不在第一版就把 broker 复杂化。


---

## 最小对象定义草案

这一节不是最终代码，只是把当前设计收成一版最小对象轮廓，方便后面实现时不再重新发明字段。

### `SharedMemoryRetrievalRequest`

```python
@dataclass(slots=True)
class SharedMemoryRetrievalRequest:
    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    event_tags: list[str] = field(default_factory=list)

    query_text: str = ""
    requested_tags: list[str] = field(default_factory=list)
    working_summary: str = ""
    retained_history: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
```

### `MemoryAssemblySpec`

```python
@dataclass(slots=True)
class MemoryAssemblySpec:
    target_slot: str = "message_prefix"
    priority: int = 0
```

### `MemoryBlock`

```python
@dataclass(slots=True)
class MemoryBlock:
    content: str
    source: str
    scope: str | None = None
    source_ids: list[str] = field(default_factory=list)
    assembly: MemoryAssemblySpec = field(default_factory=MemoryAssemblySpec)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### `MemorySource`

```python
class MemorySource(Protocol):
    async def __call__(
        self,
        request: SharedMemoryRetrievalRequest,
    ) -> list[MemoryBlock]:
        ...
```

### `MemorySourceFailure`

```python
@dataclass(slots=True)
class MemorySourceFailure:
    source: str
    error: str
    fatal: bool = False
```

### `MemoryBrokerResult`

```python
@dataclass(slots=True)
class MemoryBrokerResult:
    blocks: list[MemoryBlock] = field(default_factory=list)
    failures: list[MemorySourceFailure] = field(default_factory=list)
    attempted_sources: list[str] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)
```

### `MemorySourceRegistry`

```python
class MemorySourceRegistry:
    def register(self, source_id: str, source: MemorySource) -> None: ...
    def unregister(self, source_id: str) -> None: ...
    def list_sources(self) -> list[str]: ...
    def get(self, source_id: str) -> MemorySource | None: ...
```

### `MemorySourcePolicy`

```python
@dataclass(slots=True)
class MemorySourcePolicy:
    enabled: bool = True
    allowed_target_slots: list[str] = field(
        default_factory=lambda: [
            "system_prompt",
            "message_prefix",
            "message_history",
            "message_current_user",
        ]
    )
    required: bool = False
```

这些草案表达的边界是：

- retrieval 输入有正式一等字段
- source 输出内容块
- 内容块附带装配声明
- broker 返回成功结果和失败结果
- registry / policy 负责“有哪些 source、哪些 source 当前可用”

这里对 policy 的选择再明确一下：

- `allowed_target_slots`
  - 默认全给
  - 目标不是限制 source 的自由，而是保证值落在正式枚举里
- `default_priority`
  - 当前不保留
  - 排序权交给 source 自己声明的 `MemoryAssemblySpec.priority`

---

## 推荐的分层方式

### 1. Planner 层

负责：

- 准备共享 retrieval request
- 准备 scopes / tags / summary / retained history

不负责：

- 维护 source 名单
- 执行 retrieval

### 2. Registry / Policy 层

负责：

- 当前有哪些 source
- 哪些 source 当前启用
- 哪些 source 允许写哪些 slot

### 3. Source 层

负责：

- 真正读取 backend/source
- 判断这轮要不要返回内容
- 产出 `MemoryBlock`
- 声明 `MemoryAssemblySpec`

### 4. Broker 层

负责：

- 调度 source
- 合并成功结果
- 汇总失败结果

### 5. Assembler 层

负责：

- 校验 `MemoryAssemblySpec`
- 排序、裁剪、生成最终 payload

不负责：

- 理解 source 的检索实现
- 替 source 推断装配意图

---

## 外部 source 的接入方式

外部记忆不是靠往某个 `requested_sources` 列表里继续加字符串来接入。

更自然的方式应该是：

- 内置 source
  - 在 bootstrap 里注册到 `MemorySourceRegistry`
- 外部 source
  - 在 plugin 初始化或 runtime 扩展阶段注册到 `MemorySourceRegistry`

这样后面新 source 加入系统时：

- 不需要改 planner 的 source 枚举
- 不需要改 assembler 主线
- 只需要注册并实现统一 contract

---

## `/self` 的收口原则

`/self` 现在应该被视为正式的 file-backed memory source。

这条线后面保持：

- 只认 `today.md`
- 只认 `daily/*.md`
- 不保留旧 soul prompt 兼容逻辑
- 不额外保留 legacy bridge

也就是说：

`/self` 以后只是 registry 中的一个内置 source，不再作为特殊 prompt 注入例外存在。

---

## 非目标

这轮思路不追求下面这些事情：

- 不重新设计 `ContextAssembler`
- 不新增一层“超级 memory abstraction”
- 不为了兼容旧实现保留双轨路径
- 不把所有记忆实现塞进同一个文件
- 不用 `memory_type` 强行给所有外部内容做统一分类
- 不让 planner 成为新的 source 枚举中心
- 不让 assembler 代替 source 推断装配意图

重点只是把“长期记忆 source 如何稳定接入 runtime”这件事收成正式边界。

---

## 这份小计划想达成的结果

如果这条思路成立，后面新增一种长期记忆时，理想情况应该是：

1. 新增一个 source 实现
2. 让它注册进 `MemorySourceRegistry`
3. 让它自己声明 `MemoryAssemblySpec`
4. 如有必要，在 policy 里配置启用规则
5. 不改 runtime 主线
6. 不改 assembler 主线

也就是说：

> 新增长期记忆不再意味着“又一次上下文架构调整”，而只是一次受控扩展。
