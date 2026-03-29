# 测试模式

## 测试框架

- 后端测试主要使用 `pytest` 和 `pytest-asyncio`，配置位于 `pyproject.toml`。
- `tests/conftest.py` 中把 `anyio_backend` 固定成 `"asyncio"`，保证异步测试统一跑在 asyncio 上。
- `webui/package.json` 里没有看到 Vitest 这类前端单测框架，因此前端覆盖主要还是依赖 Python 侧的 API 和源码断言。

## 测试文件组织

- 顶层的冒烟与契约测试分布在 `tests/test_main.py`、`tests/test_agent.py`、`tests/test_gateway.py` 这类文件里。
- 大部分系统级覆盖集中在 `tests/runtime/`。
- backend 相关 runtime 测试进一步拆在 `tests/runtime/backend/` 和 `tests/runtime/control/`。
- 低层类型和契约测试位于 `tests/types/`。
- skill 相关的文件系统 fixture 位于 `tests/fixtures/skills/`。

## 测试结构

- 整体测试风格偏集成测试：很多测试会直接通过 `src/acabot/runtime/bootstrap/__init__.py` 里的 `build_runtime_components()` 组装真实运行时对象。
- 测试经常使用 `tmp_path` 构造临时配置和运行目录。
- WebUI API 测试会真正启动 `RuntimeHttpApiServer`，然后通过 HTTP 请求验证返回，见 `tests/runtime/test_webui_api.py`。
- 存储层测试会同时覆盖内存实现和 SQLite 实现，涉及 `src/acabot/runtime/storage/`。
- 可选依赖行为也有显式测试，例如 `tests/runtime/test_sqlite_memory_store.py` 中对缺少 `lancedb` 的处理。

## Mocking

- 仓库整体更偏手写 fake，而不是大量使用 mocking framework。
- 典型例子包括 `tests/runtime/test_webui_api.py` 中的 `FakeGateway`、`FakeAgent` 这类模式。
- 测试常常直接构造最小 config、registry 和 runtime state，而不是把每条依赖都 mock 掉。
- skills、subagents、model bindings、session configs 等大量场景都通过临时目录 + 真实 loader 来测。

## Fixtures 与工厂

- 共享 pytest 配线主要放在 `tests/conftest.py`。
- skill package 的样例目录和资源树放在 `tests/fixtures/skills/`。
- runtime 相关的可复用样例辅助代码放在例如 `tests/runtime/runtime_plugin_samples.py` 这种文件里。
- 很多测试会自带小型 helper，比如 `_write_config(...)` 或模型注册表 seed 函数，常见于 `tests/runtime/test_webui_api.py`。

## 覆盖情况

- 当前仓库里有 `80` 个 Python 测试文件。
- 覆盖最强的区域是 backend runtime、control plane、storage、model registry、memory 路径、subagent execution 和 WebUI API 契约。
- 前端路由和设计系统接入也会通过 Python 测试直接检查源码，例如 `tests/runtime/test_webui_api.py` 里的若干断言。
- 但浏览器层面的 Vue 页面交互覆盖相对弱，没有看到明显的前端 E2E 体系。

## 测试类型

- 低层 unit 风格测试：契约、helper、store。
- integration 风格测试：bootstrap、runtime app、subagents、tool broker、memory。
- API 测试：本地 HTTP server 和 control plane。
- 配置测试：example config、filesystem-backed loader、模型绑定等。
- 回归测试：很多 runtime 测试都明显带有“修某个边界后补断言”的味道。

## 常见模式

- 使用 `tmp_path` 隔离运行时状态，避免碰真实本地配置。
- 在测试 control-plane / model 相关接口前，会先 seed provider、preset、binding。
- 尽量构造 synthetic event 然后走真实 runtime 主线，而不是只测局部函数。
- 更偏向断言用户可见契约，而不是死盯内部实现细节。
- 当某个行为跨越多个层次时，测试往往会保留整条链路，而不是把所有接缝都打平。
