---
phase: 01
slug: system-runtime-paths
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-29
---

# Phase 01 — 验证策略

> 执行 Phase 1 时使用的分层验证契约，用来控制反馈延迟并覆盖关键风险点。

---

## 测试基础设施

| 属性 | 值 |
|----------|-------|
| **Framework** | `pytest`, `Vite build` |
| **Config file** | `pyproject.toml`, `webui/package.json` |
| **Quick run command** | `PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "system_configuration or filesystem or admin_actor_ids or gateway or SystemView or webui_real_pages"` |
| **Full suite command** | `npm --prefix webui run build && PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q` |
| **Estimated runtime** | ~20-40 秒 |

---

## 抽样频率

- **每个 task 提交后：** 运行对应 task 的快速验证命令，优先使用 `rg` 或目标 `pytest -k`
- **每个 plan wave 完成后：** 运行 `npm --prefix webui run build && PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q`
- **在 `$gsd-verify-work` 之前：** 相关完整验证必须为绿
- **最大反馈延迟：** 40 秒

---

## 按任务映射的验证表

| 任务 ID | Plan | Wave | Requirement | 测试类型 | 自动化命令 | 文件已存在 | 状态 |
|---------|------|------|-------------|----------|------------|------------|------|
| 01-01-01 | 01 | 1 | SYS-02 | source | `rg -n "def get_runtime_path_overview|filesystem_base_dir|sticky_notes_dir|long_term_memory_storage_dir|backend_session_path" src/acabot/runtime/control/config_control_plane.py` | ✅ | ⬜ pending |
| 01-01-02 | 01 | 1 | SYS-03 | source | `rg -n "/api/system/configuration|def get_system_configuration_view|apply_status|restart_required|已保存，需要重启后生效|apply_failed" src/acabot/runtime/control/http_api.py src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/config_control_plane.py` | ✅ | ⬜ pending |
| 01-01-03 | 01 | 1 | OPS-02 | unit | `PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "system_configuration or filesystem or admin_actor_ids or gateway"` | ✅ | ⬜ pending |
| 01-02-01 | 02 | 1 | SYS-01 | source | `rg -n "defineProps|@keydown.enter|ds-field" webui/src/components/EditableListField.vue` | ✅ | ⬜ pending |
| 01-02-02 | 02 | 1 | SYS-01 | source | `rg -n "EditableListField|admin_actor_ids|apiPut|ds-status" webui/src/views/AdminsView.vue` | ✅ | ⬜ pending |
| 01-02-03 | 02 | 1 | OPS-02 | unit | `PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "AdminsView or webui_real_pages"` | ✅ | ⬜ pending |
| 01-03-01 | 03 | 2 | SYS-01 | source | `rg -n "/api/system/configuration|EditableListField|高级信息|路径总览|apply_status" webui/src/views/SystemView.vue webui/src/lib/api.ts` | ✅ | ⬜ pending |
| 01-03-02 | 03 | 2 | SYS-03 | source | `rg -n '"/config/admins"|redirect: "/system"|to="/system"|to="/config/admins"' webui/src/router.ts webui/src/components/AppSidebar.vue` | ✅ | ⬜ pending |
| 01-03-03 | 03 | 2 | OPS-02 | build+unit | `npm --prefix webui run build && PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "SystemView or webui_real_pages or admins or filesystem"` | ✅ | ⬜ pending |

*状态：⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 要求

- 现有测试与构建基础设施已经覆盖本 phase 的全部验证前置条件，不需要额外 Wave 0 搭建工作。

---

## 仅手动验证的行为

| 行为 | Requirement | 为什么需要手动 | 测试说明 |
|----------|-------------|------------------|----------|
| 高级区的人话标签是否真的清楚解释了路径真源 | SYS-03 | 纯源码断言只能确认字符串存在，无法替代真实阅读感受 | 打开系统页，展开“高级信息 / 路径总览”，确认每个条目先回答“这是管什么的”，再展示实际路径值 |
| 四态结果提示是否让操作者能立刻判断下一步动作 | OPS-02 | 自动化能验证文案和状态映射，但无法完全替代真实操作理解 | 分别模拟保存成功、需重启和应用失败，确认用户能直接判断是修改输入、重试还是重启 runtime |

---

## 验证签署

- [x] 所有任务都有自动化验证，或已经被 Wave 0 前置条件覆盖
- [x] 抽样连续性满足要求：没有连续 3 个任务完全缺少自动化验证
- [x] Wave 0 已覆盖所有缺失引用
- [x] 没有使用 watch-mode 标志
- [x] 反馈延迟小于 40 秒
- [x] `nyquist_compliant: true` set in frontmatter

**批准状态：** pending
