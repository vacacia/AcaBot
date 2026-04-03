# 3c-PLAN-03: Wave 3 — WebUI 结构化日志查看器

**Phase:** 3c-logging-observability
**Wave:** 3 of 3
**Covers:** LOG-04 (WebUI 日志查看器渲染结构化字段)
**Depends on:** Wave 1 (LogEntry.extra 字段), Wave 2 (各 emit site 产生结构化日志)

---

## 目标

增强 WebUI `LogStreamPanel.vue`, 使结构化字段 (tool_name, duration_ms, run_id, token counts 等) 在日志条目中以 key-value chips 方式展示, 并支持按 extra 字段值筛选. 不重写页面, 在现有基础上增量增强.

---

## Task 1: 前端类型扩展

**文件:** `webui/src/components/LogStreamPanel.vue`

**改动:** `LogItem` type 增加 `extra` 字段

```typescript
type LogItem = {
  seq: number
  timestamp: number
  level: string
  logger: string
  message: string
  kind?: string
  extra?: Record<string, unknown>  // 新增
}
```

**向后兼容:** `extra` 是可选字段. 旧后端返回没有 `extra` 的数据时, 前端不会报错.

---

## Task 2: Extra 字段渲染

**文件:** `webui/src/components/LogStreamPanel.vue`

**改动:** 在 `<pre class="log-message">` 下方, 当 `item.extra` 非空时渲染 key-value chips

**模板改动:**

```vue
<article v-for="item in logs" :key="item.seq" class="log-line" ...>
  <div class="log-meta">
    <!-- 现有 chips 不变 -->
  </div>
  <pre class="log-message">{{ item.message }}</pre>
  <!-- 新增: 结构化字段 -->
  <div v-if="item.extra && Object.keys(item.extra).length > 0" class="log-extra">
    <span
      v-for="(value, key) in item.extra"
      :key="String(key)"
      class="extra-chip"
      :class="extraChipClass(String(key))"
      :title="String(key) + '=' + String(value)"
      @click="applyExtraFilter(String(key), String(value))"
    >
      <span class="extra-key">{{ key }}</span>
      <span class="extra-value">{{ formatExtraValue(value) }}</span>
    </span>
  </div>
</article>
```

**Script 新增:**

```typescript
// 高亮特定 key 的 chip 样式
function extraChipClass(key: string): string {
  switch (key) {
    case "run_id":
    case "thread_id":
    case "agent_id":
      return "is-context"
    case "tool_name":
      return "is-tool"
    case "duration_ms":
      return "is-timing"
    case "prompt_tokens":
    case "completion_tokens":
    case "total_tokens":
      return "is-token"
    case "error":
      return "is-error-field"
    default:
      return ""
  }
}

// 格式化 extra value 的显示文本
function formatExtraValue(value: unknown): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "number") return String(value)
  if (typeof value === "boolean") return String(value)
  if (typeof value === "string") {
    return value.length > 80 ? value.slice(0, 77) + "..." : value
  }
  // object/array: 简短 JSON
  try {
    const json = JSON.stringify(value)
    return json.length > 80 ? json.slice(0, 77) + "..." : json
  } catch {
    return String(value)
  }
}

// 点击 chip 时, 把 key=value 填入 keyword 筛选
function applyExtraFilter(key: string, value: string): void {
  keyword.value = `${key}=${value}`
}
```

---

## Task 3: Extra Chip 样式

**文件:** `webui/src/components/LogStreamPanel.vue` (`<style scoped>` 部分)

**新增样式:**

```css
.log-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.extra-chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  line-height: 1.4;
  background: rgba(100, 116, 139, 0.12);
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s;
  max-width: 100%;
  overflow: hidden;
}

.extra-chip:hover {
  background: rgba(100, 116, 139, 0.22);
}

.extra-key {
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}

.extra-key::after {
  content: "=";
  opacity: 0.5;
}

.extra-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 语义分类: context 字段 */
.extra-chip.is-context {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.extra-chip.is-context .extra-key {
  color: #4f46e5;
}

/* 语义分类: 工具字段 */
.extra-chip.is-tool {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.extra-chip.is-tool .extra-key {
  color: #047857;
}

/* 语义分类: 计时字段 */
.extra-chip.is-timing {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.extra-chip.is-timing .extra-key {
  color: #b45309;
}

/* 语义分类: token 字段 */
.extra-chip.is-token {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.extra-chip.is-token .extra-key {
  color: #1d4ed8;
}

/* 语义分类: error 字段 */
.extra-chip.is-error-field {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.extra-chip.is-error-field .extra-key {
  color: #b91c1c;
}

/* Dense 模式 */
.panel.is-dense .log-extra {
  gap: 3px;
  margin-top: 3px;
}

.panel.is-dense .extra-chip {
  padding: 0px 6px;
  font-size: 10px;
}
```

---

## Task 4: 后端 keyword 过滤扩展 (支持 extra 字段搜索)

**文件:** `src/acabot/runtime/control/log_buffer.py`

**改动:** `list_entries()` 的 keyword 过滤逻辑扩展, 使搜索覆盖 extra 字段的 key 和 value

**具体改动:**

```python
def _matches_keyword(self, item: LogEntry, keyword: str) -> bool:
    """检查一条日志是否匹配关键词.

    搜索范围: message, logger, extra 的 key 和 value.

    Args:
        item: 日志条目.
        keyword: 已 lower 化的关键词.

    Returns:
        bool: 是否匹配.
    """

    if keyword in item.message.lower():
        return True
    if keyword in item.logger.lower():
        return True
    for key, value in item.extra.items():
        if keyword in str(key).lower():
            return True
        if keyword in str(value).lower():
            return True
    return False
```

然后在 `list_entries()` 中替换:
```python
# 原:
if normalized_keyword:
    items = [
        item for item in items
        if normalized_keyword in item.message.lower() or normalized_keyword in item.logger.lower()
    ]
# 改为:
if normalized_keyword:
    items = [item for item in items if self._matches_keyword(item, normalized_keyword)]
```

**注意:** `_matches_keyword` 放在 `InMemoryLogBuffer` 类中作为静态方法或实例方法.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, LogEntry
buf = InMemoryLogBuffer(max_entries=10)
buf.append(LogEntry(timestamp=1.0, level='INFO', logger='test', message='hello', extra={'tool_name': 'bash', 'duration_ms': 42}))
buf.append(LogEntry(timestamp=2.0, level='INFO', logger='test', message='world', extra={'run_id': 'run-001'}))
# 搜索 extra value
result = buf.list_entries(keyword='bash')
assert len(result['items']) == 1
assert result['items'][0]['extra']['tool_name'] == 'bash'
# 搜索 extra key
result2 = buf.list_entries(keyword='run_id')
assert len(result2['items']) == 1
print('Keyword search with extra: OK')
"
```

---

## Task 5: 前端构建验证

**验证:**
```bash
cd /data/workspace/agent/AcaBot/webui && npm run build
```

确保 TypeScript 编译通过, 无类型错误.

---

## Task 6: 端到端手动验证

**步骤:**
1. 启动 AcaBot (或 mock 后端)
2. 触发一个工具调用 (如 bash 命令)
3. 打开 WebUI 日志页面
4. 确认日志条目中:
   - `tool_name=bash` 显示为绿色 chip
   - `duration_ms=xxx` 显示为黄色 chip
   - `run_id=xxx` 显示为紫色 chip
5. 点击 `tool_name=bash` chip, 确认 keyword 筛选器自动填入 `tool_name=bash`
6. 确认筛选后只显示包含该工具名的日志

---

## 执行顺序

```
Task 1 (类型扩展)
  |
  v
Task 2 (渲染逻辑) + Task 3 (样式)  -- 可并行
  |
  v
Task 4 (后端 keyword 扩展)          -- 独立, 可与 Task 2/3 并行
  |
  v
Task 5 (前端构建验证)
  |
  v
Task 6 (端到端验证)
```

---

## 完成标准

- [ ] `LogItem` type 包含 `extra?: Record<string, unknown>`
- [ ] 日志条目有 extra 时, 在 message 下方渲染为 key-value chips
- [ ] Chips 按语义分类着色: context(紫), tool(绿), timing(黄), token(蓝), error(红)
- [ ] 点击 chip 能填充 keyword 筛选器
- [ ] 后端 keyword 过滤覆盖 extra 字段
- [ ] Dense 模式下 chips 正确缩小
- [ ] `npm run build` 通过, 无 TypeScript 错误
- [ ] 无 extra 的日志条目不显示空白区域

---

## 风险

- **Extra 字段过多:** 某些日志可能有大量 extra 字段 (如 structlog 内部字段泄露). `STDLIB_LOG_RECORD_ATTRS` 黑名单需要在 Wave 1 中足够完整. 可以在前端添加 `v-if="Object.keys(item.extra).length < 20"` 的安全阀
- **点击筛选的精确性:** `keyword=tool_name=bash` 会匹配所有包含 "tool_name=bash" 子串的日志. 这是简单的文本匹配, 不是精确字段过滤. 精确筛选 (如 `extra.tool_name == "bash"`) 留到 v2 实现
- **样式冲突:** 新增的 `.extra-chip` 样式在 scoped CSS 内, 不会影响其他组件. 但需确认 CSS 变量 (如 `--text`, `--muted`) 在暗色主题下可读

---

*Wave 3 of 3 — Phase 3c-logging-observability*
*Created: 2026-04-03*
