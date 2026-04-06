# Model UI Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复模型 / Provider 页面里 litellm 覆盖用户输入、状态残留、Provider 配置丢失和自动 ID 不安全等高优问题。

**Architecture:** 把容易失控的前端草稿逻辑抽到纯函数 helper 中，用可执行测试先锁定自动填充、ID 清洗和 Provider 保存载荷语义；再让 Vue 页面只负责状态接线、请求取消和按钮反馈。后端只保留当前契约，不额外扩大改动面。

**Tech Stack:** Vue 3 + TypeScript + Vite；Node 内置 test runner；pytest。

---

### Task 1: 建立可测试的草稿 helper

**Files:**
- Create: `webui/src/lib/model_config_drafts.ts`
- Create: `webui/src/lib/model_config_drafts.test.ts`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行 `node --test webui/src/lib/model_config_drafts.test.ts` 确认失败**
- [ ] **Step 3: 实现 ID 清洗、自动填充保护、Provider 保存载荷 helper**
- [ ] **Step 4: 再次运行 `node --test webui/src/lib/model_config_drafts.test.ts` 确认通过**

### Task 2: 收口 ModelsView 的 litellm 与草稿状态

**Files:**
- Modify: `webui/src/views/ModelsView.vue`
- Reuse: `webui/src/lib/model_config_drafts.ts`

- [ ] **Step 1: 接入 helper，去掉 litellm 静默覆盖策略**
- [ ] **Step 2: 增加请求取消 / 响应过期校验，修复同一 Preset 内旧请求回写**
- [ ] **Step 3: Provider 切换 / 新建 Preset 时清理并重建探测状态**
- [ ] **Step 4: 删除按钮和保存/删除 loading 语义拆开**
- [ ] **Step 5: 运行 `npm --prefix webui run build` 确认前端可构建**

### Task 3: 收口 ProvidersView 的配置保真和交互反馈

**Files:**
- Modify: `webui/src/views/ProvidersView.vue`
- Reuse: `webui/src/lib/model_config_drafts.ts`

- [ ] **Step 1: 让保存载荷保留 `default_query` / `default_body`**
- [ ] **Step 2: 拆分保存/删除状态并禁用无效删除**
- [ ] **Step 3: 运行 `npm --prefix webui run build` 确认前端可构建**

### Task 4: 后端回归验证

**Files:**
- Modify: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 写失败测试，锁定 Provider 更新不会丢失隐藏配置**
- [ ] **Step 2: 运行目标 pytest 用例确认失败或覆盖新行为**
- [ ] **Step 3: 结合前端载荷策略调整后再次运行目标 pytest 用例**
- [ ] **Step 4: 记录最终验证命令与输出**
