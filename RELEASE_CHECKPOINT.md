# Runtime Release Checkpoint

当前仓库的默认主线已经切到 `runtime world`.

## 当前结论

- `main.py` 默认启动的是 `RuntimeApp`.
- 旧的 `bridge / pipeline / session / hook / plugin / store` 主路径已经删除.
- `ModelAgentRuntime + ToolBroker + MemoryBroker + ContextCompactor + ControlPlane` 都已经有真实代码和测试覆盖.
- `PYTHONPATH=src pytest -q` 当前全量通过.

## 现在这版已经成立的能力

- 多群 / 私聊统一走 `thread + run + memory + routing`.
- SQLite 持久化覆盖:
  - `threads`
  - `runs`
  - `messages`
  - `channel_events`
  - `memory_items`
- `waiting_approval` 可以跨重启恢复.
- `ControlPlane` 已支持:
  - `status`
  - `reload_plugin`
  - `switch_agent`
  - `memory show`
- runtime plugin 已经成立:
  - config-driven loading
  - targeted reload
  - built-in `ops_control`
  - built-in `reference_tools`

## 当前已知边界

- 根目录 `plugins/` 下的旧插件仍然是历史代码, 还没有迁到 runtime plugin world.
  - 例如 `plugins/notepad`
  - 例如 `plugins/napcat_tools`
- `reference` backend 已经存在 provider seam, 但真正的 `reference lookup skill` 还属于后续增强项.
- `subagent / skill orchestration` 已经有设计方向, 但不在当前 release checkpoint 范围内.

## 发布建议

如果目标是开始把 bot 当作默认主线投入使用, 当前版本已经足够作为 `release candidate`.

更准确地说:

- 可以开始以 runtime world 为唯一主线继续开发.
- 可以开始围绕 `config.example.yaml` 和 `runtime plugins` 组织新功能.
- 下一步最值得做的是:
  - 迁移根目录旧插件到 runtime plugin world
  - 继续做 `skill / subagent`
  - 逐步补管理界面或本地 WebUI
