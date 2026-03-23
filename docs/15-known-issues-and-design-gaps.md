# 已知问题和设计缺口

## 使用方式

如果你准备改某个模块，先快速扫一眼这里，看有没有相关已知问题。

如果你修掉了这里的一条，别只改代码，也要顺手更新:

- 这一篇的状态
- 对应专题文档
- 必要时 `10-change-playbooks.md`

## 1. subagent 可见性和委派边界还不够严

### 现象

当前 `delegate_subagent` 支持直接传 `delegate_agent_id`。

这条路径会优先直接查 executor registry，而不是先严格经过当前 profile 的 skill assignment / delegation policy。

结果就是:

- 只要某个 subagent executor 已注册
- 当前 agent 又能看到 `delegate_subagent` 这个工具
- 就可能直接调用一个本不该对它开放的 subagent

### 为什么这是问题

这会削弱你在 WebUI / profile 层做的能力隔离。

系统表面上看起来是:

- bot 选择携带哪些 skill / subagent

但实际 direct delegation 路径可能比这个更宽。

### 相关代码

- `src/acabot/runtime/builtin_tools/subagents.py`
- `src/acabot/runtime/subagents/broker.py`

### 修复时通常要同步

- `20-subagent.md`
- `02-runtime-mainline.md`
- 如果改变了配置语义，再看 `08-webui-and-control-plane.md`

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

