# 编码约定

## 命名模式

- Python 模块使用 snake_case，并且通常直接按职责命名，例如 `control_plane.py`、`memory_broker.py`、`session_runtime.py`。
- 类和 dataclass 使用 PascalCase，例如 `RuntimeApp`、`ThreadPipeline`、`RuntimeControlPlane`、`RouteDecision`。
- 运行时内部很多标识都使用显式命名空间字符串，例如 `qq:user:<id>`、`qq:group:<id>`、`binding:agent:aca`、`subagent:<name>`。
- Vue 页面使用 `*View.vue`，公用组件使用 PascalCase 文件名，例如 `LogStreamPanel.vue`、`StatusCard.vue`。

## 代码风格

- Python 文件几乎都会先写 `from __future__ import annotations`。
- 生产代码广泛使用类型标注，尤其是 `src/acabot/runtime/contracts/`、`src/acabot/runtime/model/`、`src/acabot/runtime/control/`。
- 模块风格偏向“小 helper + 显式 builder”，而不是一个类里藏很多隐式初始化逻辑。
- Docstring 很常见，而且大量使用中文来解释模块边界和设计意图。
- 代码整体更偏显式组合、纯数据对象和边界清晰的 service，而不是依赖框架魔法。

## 导入组织

- 导入顺序通常是标准库、第三方库、项目内模块。
- 需要隔离循环依赖或仅用于类型提示时，会使用 `TYPE_CHECKING`，例如 `src/acabot/runtime/bootstrap/builders.py`。
- 包内部多用相对导入，顶层入口则常用绝对包导入，例如 `from acabot.config import Config`。
- 前端模块使用标准 ES import，路径通常保持比较浅，例如 `./views/HomeView.vue`、`./lib/api`。

## 错误处理

- 可选依赖通常会被显式保护，并给出有针对性的 `RuntimeError`，例如 `src/acabot/gateway/napcat.py` 和 `src/acabot/runtime/bootstrap/builders.py`。
- pipeline 和 app 生命周期代码会在失败时主动做清理，而不是默认让进程退出，见 `src/acabot/runtime/app.py` 和 `src/acabot/runtime/pipeline.py`。
- HTTP API 会把预期错误统一包装成 JSON 错误返回，逻辑在 `src/acabot/runtime/control/http_api.py`。
- 配置读取大量使用 `dict.get(...)` 和默认值，而不是假定字段一定存在。

## 日志

- 后端模块统一使用 `logging.getLogger("acabot....")` 风格的命名 logger，例如 `acabot.runtime.app`、`acabot.gateway`。
- 日志里经常带上 `event_id`、`run_id`、`thread_id`、`agent_id` 这类运行时标识，方便排查。
- 系统会通过 `src/acabot/runtime/control/log_buffer.py` 维护一段内存日志窗口，供 WebUI 查看。
- routing、model resolution、compaction、delivery 等关键链路都有较多 debug 级日志。

## 注释

- 注释主要用于解释架构意图、迁移痕迹和一些容易踩坑的行为，而不是逐行翻译代码。
- 仓库里会保留“踩坑记录”类注释，例如 `src/acabot/runtime/control/http_api.py` 对静态目录路径问题的说明。
- 对并发、生命周期这类不直观逻辑，允许使用较长的解释性注释，例如 `src/acabot/runtime/pipeline.py` 中关于 compaction 的说明块。

## 函数设计

- 公共函数和方法通常会写带 Args/Returns 的 docstring。
- builder 风格命名非常常见，例如 `build_runtime_components`、`build_memory_broker`、`build_long_term_memory_source`。
- 决策型函数也很多，例如 `resolve_surface`、`resolve_routing`、`resolve_admission`、`resolve_context`。
- IO 重、跨服务边界的逻辑通常是 `async`；纯解析或配置 helper 通常保持同步。

## 模块设计

- runtime 内部主要按领域拆分目录，而不是只按 MVC / service / util 这种通用层次拆。
- `src/acabot/runtime/__init__.py` 承担了一个大的 facade export 角色，把 runtime 对外稳定面集中导出。
- skills、subagents、profiles、sessions、model bindings 等能力都走文件系统 catalog / loader，这是一条很明确的设计主线。
- 测试目录和正式代码的领域边界比较一致，尤其是 `tests/runtime/` 这层。
