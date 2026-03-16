# model_registry

这一篇讲模型真源和“本次 run 到底用哪个模型”这条链。

关键文件:

- `src/acabot/runtime/model/model_registry.py`
- `src/acabot/runtime/model/model_resolution.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/control/control_plane.py`

## 先讲结论

在 AcaBot 里，模型不是简单一个字符串。

真正生效的是三层组合:

- provider
- preset
- binding

最后再解析成 `RuntimeModelRequest`，交给 agent 发请求。

## 三层对象分别是什么

### provider

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

### preset

表示一个可复用的具体模型预设。

比如:

- 用哪个 provider
- 模型名
- `context_window`
- `supports_tools`
- `supports_vision`
- `max_output_tokens`
- `model_params`

### binding

表示“谁用哪个 preset”。

现在 target_type 主要有:

- `global`
- `agent`
- `system`

其中 `system:compactor_summary` 比较特殊，用来控制 compactor summary 模型。

## `RuntimeModelRequest` 才是最终执行形态

provider / preset / binding 最后会被拉平成 `RuntimeModelRequest`。

这里面已经是 agent 真正拿去请求模型的终态信息了，比如:

- `provider_kind`
- `model`
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
- 校验 registry
- 提供 upsert / delete / reload
- 计算 impact
- 解析 run request 和 summary request
- 做 health check

### 这里的“权威真源”是什么

是 filesystem-backed 的目录，不是代码里硬编码的模型常量。

也就是说，WebUI 和控制面改模型，本质上是在改这些文件系统真源，再 reload。

## 模型解析优先级

看 `resolve_run_request()`，当前大致顺序是:

1. agent binding
2. profile 里显式 `default_model`
3. legacy global default model
4. profile 生效后的默认模型

这点很关键。

如果某个 agent 明明 profile 写了默认模型，却没生效，先看是不是被 binding 覆盖了。

## summary 模型是另一条线

`resolve_summary_request()` 不是简单复用主模型。

它有自己的优先级，大致是:

1. profile 的 `summary_model_preset_id`
2. profile 的 `summary_model`
3. `system:compactor_summary` binding
4. legacy summary model
5. 回退到 primary request

所以你改 compactor summary 行为时，不要只盯主模型。

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

profile 更像“某个 agent 的默认倾向”，而 model registry 才是正式模型配置体系。

简单说:

- profile 说“我默认想用哪个模型”
- registry 决定“系统最后准备用什么 provider / preset / binding 真正执行”

## 哪些改动会碰这里

- WebUI 里改 provider / preset / binding
- 给某个 agent 指定专用模型
- 给 compactor summary 指定专用模型链
- 新增 vision 模型支持
- 做模型健康检查或模型切换

## 常见误区

### 1. 把 provider 当模型

provider 只是连接层，不是具体模型定义。

### 2. 只改 profile，不改 binding / preset

这样很容易出现“配置看起来改了，实际跑的还是旧模型”。

### 3. 忘了 summary 模型是单独的一条线

context compaction 的行为可能和主对话模型不同。

### 4. 只改 UI，不看 registry 校验

很多错误其实是 `validate()` 阶段就能挡住的。

## 当前已知实现特点

这块暂时没看到特别扎眼的硬 bug，但有几个实现特点值得写进文档，不然以后容易误判:

- run 模型和 summary 模型是两条解析链，不要假设它们永远一致
- profile 默认模型只是候选，不是最终真源
- binding 的优先级高于 profile 默认模型

如果以后你改了这几个优先级，必须同步这篇文档。

## 如果改这里，通常同步哪些文档

- `13-model-registry.md`
- `08-webui-and-control-plane.md`
- 如果影响 prompt compaction summary，再看 `05-memory-and-context.md`

## 读源码顺序建议

1. `src/acabot/runtime/model/model_registry.py`
2. `src/acabot/runtime/model/model_resolution.py`
3. `src/acabot/runtime/bootstrap/`
4. `src/acabot/runtime/control/control_plane.py`
5. `src/acabot/webui/app.js`
