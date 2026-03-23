
## `/self`

### 设计理念(不准修改)

这一层记录的是：
   - Aca 自己经历了什么, 这一天正在和谁、在哪些群互动
   - Aca 当前有哪些持续中的状态、任务和承诺

这层的目标不是存“人物资料”或“群资料”，也不是人格 prompt 的替代品。
   - 人格设定在配置 prompt 里
   - 和具体用户、具体群强绑定的信息应该放 sticky note
   - `/self` 是 Aca 的自我连续性空间

`/self` 具备这些特征：
   - 由 Aca 在自己的 computer 里管理
   - 会把今天、昨天...的内容注入 Aca 上下文
   - `self` 下的 md 文件能在 WebUI 里展示目录结构并编辑

### 当前代码现状

已经落地的部分主要有三条线：

1. **前台 world 里已经有 `/self` 这条文件根**
   - 代码在 `src/acabot/runtime/computer/world.py`
   - 宿主机目录布局在 `src/acabot/runtime/computer/workspace.py`
   - 前台 agent 可以看见 `/self`
   - subagent 默认看不见 `/self`

2. **运行时有一套 `SoulSource` 文件真源**
   - 代码在 `src/acabot/runtime/soul/source.py`
   - bootstrap 在 `src/acabot/runtime/bootstrap/__init__.py`
   - 默认维护固定文件：
     - `identity.md`
     - `soul.md`
     - `state.yaml`
     - `task.md`

3. **pipeline 目前注入的是 soul 文本，不是广义 `/self` 扫描结果**
   - 代码在 `src/acabot/runtime/pipeline.py`
   - 当前行为是 `SoulSource.build_prompt_text()` 生成稳定文本，然后写到 `ctx.metadata["soul_prompt_text"]`
   - `RetrievalPlanner` 再把这段文本作为 `soul_context` prompt slot 注入

此外，控制面和 WebUI 现在已经有 `/api/self/*` 这套接口，但它本质上是 **兼容别名**：

- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

现在的 `list_self_files / get_self_file / put_self_file / post_self_file` 实际上都转到了 `SoulSource`。也就是说，当前代码里“self API”和“soul 文件”在控制面层是合并的。

所以这一层的真实现状可以直接概括成一句话：

> 当前代码已经有 `/self` 的文件可见性，也有 soul 文件真源和 prompt 注入，但还没有做成 `00` 里那种“按天维护、自我连续、最近几天自动进上下文”的完整 self memory。

