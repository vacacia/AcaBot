# WebUI V2 Usable Shell Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a usable new WebUI shell that replaces the old IA with 首页 / 配置 / 会话 / 系统 and supports real viewing/editing for the highest-value config flows.

**Architecture:** Keep the current HTTP server and control plane, but add small targeted API support for logs and plugin config. Replace the old static WebUI with a new simpler frontend that talks to existing APIs where possible and hides old implementation concepts.

**Tech Stack:** Python control plane + static HTML/CSS/JS WebUI

---

### Task 1: Add failing tests for new WebUI/API requirements

**Files:**
- Modify: `tests/runtime/test_webui_api.py`

- [ ] Add a failing test for `/api/system/logs`
- [ ] Add a failing test for plugin config read/write endpoints
- [ ] Add/update a failing static smoke test for new navigation/content expectations
- [ ] Run targeted pytest and confirm failure

### Task 2: Add minimal backend APIs for WebUI v2

**Files:**
- Create: `src/acabot/runtime/control/log_buffer.py`
- Modify: `src/acabot/main.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`

- [ ] Add in-memory log ring buffer + logging handler
- [ ] Expose `list_recent_logs()` via control plane
- [ ] Expose runtime plugin config list/update via config control plane
- [ ] Add HTTP endpoints for logs and plugin config
- [ ] Run targeted pytest and confirm pass

### Task 3: Replace old WebUI with new v2 shell

**Files:**
- Modify: `src/acabot/webui/index.html`
- Modify: `src/acabot/webui/styles.css`
- Modify: `src/acabot/webui/app.js`

- [ ] Replace static HTML with new shell layout
- [ ] Replace CSS with new layout/system styles
- [ ] Replace JS with new app that implements:
  - 首页状态 + 日志
  - 配置: Bot / 模型 / Prompts / Plugins / Skills / Subagents
  - 会话: 列表 + AI / 输入处理 / 其他
  - 系统: 日志 / Backend / 审批 / 资源
- [ ] Make prompts show only name + content in UI
- [ ] Make tools/skills selection use catalog-backed checkboxes
- [ ] Add plugin enable/disable UI based on new API

### Task 4: Wire real save flows for highest-value pages

**Files:**
- Modify: `src/acabot/webui/app.js`

- [ ] Bot page save via profiles + model bindings APIs
- [ ] Prompt CRUD via prompt APIs
- [ ] Plugin toggle + reload via plugin APIs
- [ ] Session save via existing rules/profile/model APIs with simplified UI model
- [ ] Run targeted pytest and manual smoke check

### Task 5: Verification

**Files:**
- None

- [ ] Run: `PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q`
- [ ] Run a broader webui/control suite
- [ ] Open the new WebUI in browser and verify key flows manually
