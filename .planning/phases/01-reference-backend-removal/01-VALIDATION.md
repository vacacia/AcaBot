---
phase: 01
slug: reference-backend-removal
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-04
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for Reference Backend deletion evidence.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | shell checks + `pytest` targeted smoke via `uv run` |
| **Config file** | `pyproject.toml`, `.planning/phases/01-reference-backend-removal/01-VERIFICATION.md` |
| **Quick run command** | `bash -lc 'test -z "$(find src/acabot/runtime/references -type f ! -path '\''*/__pycache__/*'\'' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml && ! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py'` |
| **Full suite command** | `bash -lc 'test -z "$(find src/acabot/runtime/references -type f ! -path '\''*/__pycache__/*'\'' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml && PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable && ! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py'` |
| **Estimated runtime** | ~4 seconds |

---

## Validation Architecture

Phase 01 的验证结构只做一件事: 证明 Reference Backend 真的已经从仓库主路径消失, 同时过渡插件还活着。

- 第一层是 source deletion check。这里必须用 `find ... ! -path '*/__pycache__/*'` 过滤缓存目录, 因为 `__pycache__` 不是源码残留, 也不是 Phase 01 回归。
- 第二层是 symbol zero-hit check。它覆盖 `src`、`tests`、`config.example.yaml`, 防止“文件删了, import 还留着”这种半截清理。
- 第三层是 transition smoke。`BackendBridgeToolPlugin` 仍然是过渡期代码, 所以 Phase 01 不能只验证删除, 还要验证它没被 reference backend 拖死。
- 第四层是 config and wiring cleanup。`config.example.yaml`、bootstrap、app 必须一起检查, 不然会出现配置没了但 wiring 还在, 或者 wiring 没了但注释配置还留着的假完成状态。

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | REF-01 | static + git-backed current-state check | `test -z "$(find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml` | ✅ | ✅ green |
| 01-02-01 | 02 | 2 | REF-02 | unit smoke | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | ✅ | ✅ green |
| 01-02-02 | 02 | 2 | REF-03 | static | `! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py` | ✅ | ✅ green |

---

## Wave 0 Requirements

- None. 当前 phase 所需的 shell、`rg`、`uv`、`pytest` 都已存在, 没有额外的 Wave 0 缺口。
- `__pycache__` 不能当成源码残留。所有 REF-01 检查都必须忽略 `src/acabot/runtime/references/__pycache__/`.
- 不要用 `test ! -d src/acabot/runtime/references/` 当硬门槛。当前仓库会重新生成缓存目录, 这个目录存在不代表 reference backend 回来了。

---

## Manual-Only Verifications

All Phase 01 behaviors have automated verification.

---

## Validation Sign-Off

- [x] All requirements have automated commands
- [x] No Wave 0 setup gap remains
- [x] `nyquist_compliant: true` set in frontmatter
- [x] `__pycache__` handling is explicit
- [x] Validation commands only cover REF-01, REF-02, REF-03

**Approval:** ready
