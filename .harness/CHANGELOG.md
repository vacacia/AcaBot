# Harness Changelog

## 2026-04-06
- 创建 `.harness/CHANGELOG.md`，作为 harness 自身变更记录入口。
- 更新 `.harness/features.json`，补充模型与模型供应商页面问题追踪：
  - `model-ui-001`：litellm 探测结果静默覆盖用户手动编辑。
  - `model-ui-002`：Provider / Preset 切换时 litellm 信息残留、重探测契约不清。
  - `model-ui-003`：Provider 页面保存会丢失 `default_query` / `default_body`。
  - `model-ui-004`：Preset / Provider ID 缺少文件系统安全约束。
  - `model-ui-005`：模型与 Provider 页面存在明显反人类交互与状态反馈问题。
- 更新 `.harness/AGENTS.md`，明确部署时绝对不能碰 `acabot-napcat`，并补充只允许针对 `acabot` 的安全命令。
- 更新 `.harness/AGENTS.md`，补充 WebUI 源码目录、构建产物目录，以及前端改动后的标准 build / 重载流程。
- 新增 `.harness/failure-patterns/FP-005.md`，记录 SQLite 失败写入污染事务、导致后续 scheduler / run 链路一起 `database is locked` 的教训，并同步更新 `.harness/AGENTS.md` 索引与处置规则。
