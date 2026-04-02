# 模型注册表

本文档讲模型真源和"本次 run 到底用哪个模型"的解析链。

## 四层模型体系

在 AcaBot 里模型不是一个字符串，而是四层组合，最终解析成 `RuntimeModelRequest` 交给 agent 发请求：

| 层 | 含义 | 示例 |
|----|------|------|
| **model_provider** | 供应商连接层（base_url、api_key、默认 headers） | `openai_compatible`、`anthropic`、`google_gemini` |
| **model_preset** | 可复用的具体模型预设（provider、模型名、context_window、task_kind、capabilities、max_output_tokens、model_params） | — |
| **model_target** | 系统中哪个消费位点需要模型 | `agent:aca`、`system:compactor_summary`、`system:ltm_extract`、`plugin:memory_plugin:embedder` |
| **model_binding** | 某个 target 绑定哪条主 preset 和 fallback 链 | target_id + preset_ids |

Target 主要三类：`agent:<agent_id>`（主回复）、`system:<name>`（系统能力如 compaction/image caption/LTM）、`plugin:<plugin_id>:<slot_id>`（插件）。

Binding 只认 `target_id + preset_ids`，不再从 profile 或 session 私有字段回退模型。

## RuntimeModelRequest

provider/preset/binding 最终被拉平成 `RuntimeModelRequest`——agent 真正拿去请求模型的终态：`provider_kind`、`model`、`task_kind`、`capabilities`、`supports_tools`、`supports_vision`、`provider_params`、`model_params`、`execution_params`、`fallback_requests`。

调试"为什么这个 run 用这个模型"时追 RuntimeModelRequest 的解析过程。

## FileSystemModelRegistryManager

真正入口，职责：从文件系统读 provider/preset/binding、维护 target catalog、校验 registry、提供 upsert/delete/reload、计算 impact、解析 target request、做 health check。

权威真源是 filesystem-backed 的目录（`runtime_config/models/` 下的 providers/presets/bindings），不是代码里硬编码的常量。控制面改模型本质上是改文件系统真源再 reload。

## 模型解析路径

1. 模块确定自己要哪个 `model_target`
2. Registry 用 `model_binding` 找主 preset 和 fallback preset 链
3. 解析成 `RuntimeModelRequest`

没有 profile 默认模型、session 私有 preset、summary 私有模型这些旁路。

## Impact 和删除级联

Registry 有 provider/preset/binding 三层 impact 计算：删 provider/preset 时检查下游引用。这是 WebUI 做"删除前影响面提示"的基础。

## Health Check

`health_check()` 用 `LitellmAgent.complete()` 实际发一次最小请求，不是纯静态校验。测的是：registry 能不能解析成 request、provider 连不连得通、这组参数能不能完成一次最小 completion。

## Profile 与模型的关系

Profile 不是模型真源。Profile 只负责 agent 身份、prompt、工具、skills 和 computer policy。模型来源只在 model registry 里。

## 实现特点

- 不同消费位点走不同 `model_target`，不要假设天然共用一条模型链
- Plugin target 允许在插件未加载时先以 `binding_state=unresolved_target` 留在控制面
- Target 当前缺失、`task_kind` 不匹配或缺少 required capabilities 时，binding 不应被解析成 live request

## 关键文件

| 文件 | 职责 |
|------|------|
| `runtime/model/model_registry.py` | FileSystemModelRegistryManager |
| `runtime/model/model_resolution.py` | 模型解析逻辑 |
| `runtime/control/model_ops.py` | 控制面模型操作 |
| `runtime/control/control_plane.py` | 状态聚合 |
| `runtime/control/config_control_plane.py` | 配置真源读写 |
| `runtime/control/http_api.py` | HTTP 适配 |
