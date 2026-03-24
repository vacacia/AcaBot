
## `/self`

### 设计理念(不准修改)

这一层记录的是：
   - Aca 自己经历了什么, 这一天正在和谁、在哪些群互动
   - Aca 当前有哪些持续中的状态、任务和承诺

这层的目标不是存“人物资料”或“群资料”，也不是人格 prompt 的替代品。
   - 人格设定在配置 prompt 里
   - 和具体用户、具体群强绑定的信息应该放 sticky note
   - `/self` 是 Aca 的自我连续性空间
   - 会出现自己和**其他人**的交互, 但是不是为了沉淀这些对象本身的长期资料

`/self` 具备这些特征：
   - 由 Aca 在自己的 computer 里管理
   - 会把今天、昨天...的内容注入 Aca 上下文
   - `self` 下的 md 文件能在 WebUI 里展示目录结构并编辑

### 结构(修改方向):
```
/self/
  today.md
  daily/
    2026-03-23.md
    2026-03-22.md
```
today.md: 今天的自我连续性记录(偏日志, 是 LLM 主动调用工具记录的在干什么的极其简短的摘要, 不涉及具体信息, 需要具体信息应该 bot 自己查聊天记录..)
daily/: 昨天、前天的整理稿(偏总结)

不是 thread workspace 的普通子目录

提供一个工具追加到 today.md, 防止并发写冲突.
不是废话日志, 没有意义的事情不追加进 today.md

例如 
```
[qq:group:123456 time=xxx] vi(qq:1234567)让我xx
[qq:group:123456 time=xxx] vi(qq:1234567)交代的事情完成了
---

总结里就可以合并这两个事情

```

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

