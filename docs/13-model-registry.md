# model_registry

这一篇讲模型真源和“本次 run 到底用哪个模型”这条链。

关键文件:

- `src/acabot/runtime/model/model_registry.py`
- `src/acabot/runtime/model/model_resolution.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/control/control_plane.py`

## 先讲结论

在 AcaBot 里，模型不是简单一个字符串。

真正生效的是四层组合:

- model_provider
- model_preset
- model_target
- model_binding

最后再解析成 `RuntimeModelRequest`，交给 agent 发请求。

## 四层对象分别是什么

### model_provider

表示供应商连接层。

现在正式支持:

- `openai_compatible`
- `anthropic`
- `google_gemini`

provider 管的是:

- `base_url`
- `api_key_env / api_key`
- 默认 headers / query / body

它不直接表示某个具体模型。

### model_preset

表示一个可复用的具体模型预设。

比如:

- 用哪个 provider
- 模型名
- `context_window`
- `task_kind`
- `capabilities`
- `max_output_tokens`
- `model_params`

### model_target

表示“系统里哪个正式消费位点需要模型”。

现在 target 主要分三类:

- `agent:<agent_id>`
- `system:<name>`
- `plugin:<plugin_id>:<slot_id>`

比如:

- `agent:aca`
- `system:compactor_summary`
- `system:image_caption`
- `system:ltm_extract`
- `plugin:memory_plugin:embedder`

### model_binding

表示“某个 model_target 绑定哪条主 preset 和哪条 fallback 链”。

`model_binding` 只认 `target_id + preset_ids`，不再从 profile 或 session 私有字段回退模型。

## `RuntimeModelRequest` 才是最终执行形态

provider / preset / binding 最后会被拉平成 `RuntimeModelRequest`。

这里面已经是 agent 真正拿去请求模型的终态信息了，比如:

- `provider_kind`
- `model`
- `task_kind`
- `capabilities`
- `supports_tools`
- `supports_vision`
- `provider_params`
- `model_params`
- `execution_params`
- `fallback_requests`

所以如果你在调试“为什么这个 run 用的是这个模型”，真正该追的是它怎么被解析成 `RuntimeModelRequest`。

## `FileSystemModelRegistryManager` 是真正入口

这个 manager 做了几件重要的事:

- 从文件系统读 provider / preset / binding
- 维护 target catalog
- 校验 registry
- 提供 upsert / delete / reload
- 计算 impact
- 解析 target request
- 做 health check

### 这里的“权威真源”是什么

是 filesystem-backed 的目录，不是代码里硬编码的模型常量。

也就是说，当前控制面改模型，本质上是在改这些文件系统真源，再 reload。
现在真正会碰到的入口主要是：

- `src/acabot/runtime/control/model_ops.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/config_control_plane.py`

## 模型解析现在只走 target

当前正式解析路径很简单:

1. 模块先确定自己要哪个 `model_target`
2. registry 用 `model_binding` 找主 preset 和 fallback preset 链
3. 解析成 `RuntimeModelRequest`

例子:

- 主回复走 `agent:<agent_id>`
- compactor 走 `system:compactor_summary`
- image caption 走 `system:image_caption`
- LTM 走自己的 `system:ltm_*`
- 插件走 `plugin:<plugin_id>:<slot_id>`

这里已经没有 profile 默认模型、session 私有模型 preset、summary 私有模型这些正式旁路。

## impact 和删除级联

model registry 里有一套 impact 计算:

- provider impact
- preset impact
- binding impact

删 provider / preset 时会看有没有被下游引用。

这也是 WebUI / control plane 能做“删除前影响面提示”的基础。

## health check 真在测什么

`health_check()` 会用 `LitellmAgent.complete()` 实际发一次最小请求。

所以它不是纯静态校验，而是:

- registry 能不能解析成 request
- provider 连不连得通
- 这组参数能不能真完成一次最小 completion

## 这层和 profile 的关系

profile 不是模型真源。

profile 现在只负责 agent 身份、prompt、工具、skills 和 computer policy；真正的模型来源只在 model registry 里。

## 哪些改动会碰这里

- 控制面里改 provider / preset / binding
- 给某个 agent 指定专用模型
- 给 compactor summary 指定专用模型链
- 新增 vision 模型支持
- 做模型健康检查或模型切换

## 常见误区

### 1. 把 provider 当模型

provider 只是连接层，不是具体模型定义。

### 2. 只改控制面表面，不看 target / binding 校验

很多错误其实是 `validate()` 阶段就能挡住的。

## 当前已知实现特点

这块暂时没看到特别扎眼的硬 bug，但有几个实现特点值得写进文档，不然以后容易误判:

- 不同消费位点走不同 `model_target`，不要假设它们天然共用一条模型链
- plugin target 允许在插件未加载时先以 `binding_state=unresolved_target` 留在控制面
- target 当前缺失、`task_kind` 不匹配，或者缺少 required capabilities 时，binding 不应再被解析成 live request

如果以后你改了 target/binding 的状态机，必须同步这篇文档。

## 如果改这里，通常同步哪些文档

- `13-model-registry.md`
- `08-webui-and-control-plane.md`
- 如果影响 prompt compaction summary，再看 `05-memory-and-context.md`

## 读源码顺序建议

1. `src/acabot/runtime/model/model_registry.py`
2. `src/acabot/runtime/model/model_resolution.py`
3. `src/acabot/runtime/control/model_ops.py`
4. `src/acabot/runtime/control/control_plane.py`
5. `src/acabot/runtime/control/http_api.py`
6. `src/acabot/runtime/control/config_control_plane.py`
7. 如果还要看当前静态页面壳, 再看：
   - `src/acabot/webui/index.html`
   - `src/acabot/webui/assets/`
