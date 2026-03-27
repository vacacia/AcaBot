# 当前进展 Handoff

phase 1 已经提交为 `cf555d5`，正式模型真源现在是 `model_provider / model_preset / model_target / model_binding`，而当前实际在用的 Python 环境固定是 `/home/acacia/AcaBot/.venv`，`pip` 也已经通过 `.venv/pip.conf` 切到腾讯镜像。
`long_term_memory` 第一版已经接进 runtime：打开 `runtime.long_term_memory.enabled` 后，会自动装配 `LanceDbLongTermMemoryStore`、`CoreSimpleMemWritePort`、`CoreSimpleMemMemorySource` 和 `LongTermMemoryIngestor`，实现代码集中在 `src/acabot/runtime/memory/long_term_memory/`，但 `system:ltm_extract`、`system:ltm_query_plan`、`system:ltm_embed` 这三个 binding 仍然需要先配置好。
当前最可靠的验收方式是用 `PYTHONPATH=src python -m pytest ...` 跑本地纯逻辑测试，因为 worktree 里直接执行 `python` 会走根目录 `.venv`；最近一轮整套非后端验收结果是 `458 passed in 28.88s`，下一步是拿到 reviewer 复核通过后 commit。
