# 已知问题和设计缺口

## 使用方式

如果你准备改某个模块，先快速扫一眼这里，看有没有相关已知问题。

如果你修掉了这里的一条，别只改代码，也要顺手更新:

- 这一篇的状态
- 对应专题文档
- 必要时 `10-change-playbooks.md`

## 1. subagent 第一版还不支持递归和 approval resume

### 现象

当前 subagent 已经有明确边界:

- 定义真源是文件系统 `SUBAGENT.md`
- 可见性只认 session `visible_subagents`
- child run 默认 `visible_subagents=[]`

所以第一版现在不会:

- 递归委派 subagent
- 把 child run 挂进 `waiting_approval`
- 让 approval replay 恢复 subagent child run

### 为什么这是问题

这不是 bug, 是当前刻意保守的产品边界。

但如果以后想做:

- 更复杂的多级委派
- 可审批的子任务
- 真正长期运行的后台 worker

那就必须重新设计 child run 生命周期, 不能直接把现在这版短生命周期 subagent 往上硬加。

### 相关代码

- `src/acabot/runtime/builtin_tools/subagents.py`
- `src/acabot/runtime/subagents/broker.py`
- `src/acabot/runtime/subagents/execution.py`
- `src/acabot/runtime/pipeline.py`

### 修复时通常要同步

- `20-subagent.md`
- `02-runtime-mainline.md`
- 如果改变 session 语义, 再看 `08-webui-and-control-plane.md`

### 建议状态

`open`

## 2. skill 设计有问题
参考 `docs/18-skill.md`
### 建议状态

`open`

## 3. computer 的文件操作和 backend 语义还没完全统一

### 现象

`bash` 和内部 shell session 会按 effective backend 走，但 `read / write / edit` 这组文件操作现在仍然偏向 host 路径读写。

也就是说，当前这两层能力还不是完全一套 backend 语义。

### 为什么这是问题

如果以后认真推进:

- docker backend
- remote backend
- 更严格的 sandbox

那“命令跑在哪”和“文件读写落在哪”可能会不一致。

### 相关代码

- `src/acabot/runtime/computer/`
- `src/acabot/runtime/builtin_tools/computer.py`

### 修复时通常要同步

- `12-computer.md`
- `02-runtime-mainline.md`
- 如果影响工具暴露，再看 `19-tool.md`

### 建议状态

`open`

## 4. 附件总大小限制是在 staging 后才判定

### 现象

当前附件会先尝试下载 / 落地，然后再做累计大小检查。

超限后 snapshot 会标成失败，但已经落下来的文件不一定被立即清理。

### 为什么这是问题

长时间跑起来后，这会带来:

- workspace 膨胀
- 临时文件残留
- “逻辑上失败了，但磁盘已经写了”的不一致

### 相关代码

- `src/acabot/runtime/computer/`

### 修复时通常要同步

- `12-computer.md`
- 如果影响图片 / 文件流程，再看 `10-change-playbooks.md`

### 建议状态

`open`

## 6. WebUI 日志当前只有“最近窗口”，还不是完整历史检索

### 现象

现在 WebUI 日志已经支持:

- 首次快照
- `after_seq` 增量刷新
- 首页预览
- 独立日志页

但底层真源仍然只是 `InMemoryLogBuffer` 这段 ring buffer。

### 为什么这是问题

这意味着:

- 进入页面前的一小段日志能看到
- 但更早的日志一旦被 ring buffer 顶掉，就无法再从 WebUI 往前查
- 搜索范围也只覆盖当前缓冲窗口，不是完整历史

### 相关代码

- `src/acabot/runtime/control/log_buffer.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`
- `webui/src/components/LogStreamPanel.vue`
- `webui/src/views/HomeView.vue`
- `webui/src/views/LogsView.vue`

### 修复时通常要同步

- `08-webui-and-control-plane.md`
- 如果引入文件历史或持久化日志，再看 `09-config-and-runtime-files.md`

### 建议状态

`open`

## 7. bootstrap 命名和入口还带着新旧交替痕迹

### 现象

这轮读 runtime 时，一个直接感受到的现象是：

- `bootstrap/` 目录已经收成新的入口形状
- 但历史命名和旧猜测路径还容易误导阅读
- 如果按旧习惯去猜文件名，很容易先撞到不存在的入口

这说明这块最近确实在收边界，但收口还没完全把“旧入口印象”清干净。

### 为什么这是问题

这会带来两个成本：

- 阅读成本
  - 新人很容易先按旧命名找入口
- 文档成本
  - 文档如果没持续对齐，很容易继续把人带到历史路径上

### 相关代码

- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/bootstrap/__init__.py`

### 修复时通常要同步

- `01-system-map.md`
- `02-runtime-mainline.md`
- `09-config-and-runtime-files.md`

### 建议状态

`open`

## 8. sticky notes 当前是双真源混合态

### 现象

当前 sticky notes 在实现上已经分成两种真源:

- `user / channel`
  - 走 file-backed 真源
- `relationship / global`
  - 仍然会走 `MemoryStore`

也就是说，这一层已经明显在往“分层真源”走，但还没有完全收敛成统一产品表达。

### 为什么这是问题

这会带来两个直接后果：

- 语义理解成本
  - 同样叫 sticky notes，不同 scope 背后其实不是一套真源
- 产品表达成本
  - WebUI、control plane、后续记忆设计都需要一直意识到这层差异

### 相关代码

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- `src/acabot/runtime/memory/file_backed/retrievers.py`
- `src/acabot/runtime/memory/sticky_notes.py`

### 修复时通常要同步

- `05-memory-and-context.md`
- `17-2-memory-stickynotes.md`
- `08-webui-and-control-plane.md`

### 建议状态

`open`

## 9. `scope` 和 `memory_type` 这两个维度的语义还没完全摆正

### 现象

当前代码里：

- `scope`
  - 已经比较清楚地表示归属空间
- `memory_type`
  - 还更像一个存储标签

这两个维度都存在，但它们在设计上的地位还没有完全收清楚。

### 为什么这是问题

这会影响后面三条线的表达稳定性：

- retrieval 规划
- memory 存储形状
- WebUI / control plane 的产品语义

如果这两个维度继续混着用，后面很容易让“归属空间”和“内容类型”在不同模块里承担不同含义。

### 相关代码

- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/control/control_plane.py`

### 修复时通常要同步

- `03-data-contracts.md`
- `05-memory-and-context.md`
- `17-0-memory.md`
- `17-3-memory-long-term-memory.md`

### 建议状态

`open`
