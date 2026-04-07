# context_assembly 约定

## system prompt 规则

**所有 system prompt 文案必须放在 `src/acabot/runtime/context_assembly/prompts/` 目录下的独立文本文件里**。

1. 不要把 system prompt 文案散落在代码里
2. 即使只是一句话的提醒，也要放进 `prompts/*.md` 文件，再由代码读取
3. Python 代码负责：
   - 选择是否注入该 prompt
   - 传入格式化变量
   - 控制优先级与拼装顺序
4. 每个静态 prompt 文件都应该带清晰的 XML 包裹标记，例如：
   - 开头：`<system-reminder name="workspace_restrictions">`
   - 结尾：`</system-reminder>`
5. 测试尽量只校验这些稳定标记是否被正确拼装，不要把整段 prompt 正文硬编码进测试；这样 prompt 内容可以持续迭代，结构仍然可验证

## 当前目录结构

- `prompts/`：system prompt 文案源文件
- `assembler.py`：决定注入哪些 prompt、注入顺序、格式化变量
- `contracts.py`：上下文组装契约
- `payload_json_writer.py`：调试/落盘相关辅助

## 当前 system prompt 结构

当前发给模型的最终 system prompt 由 `ContextAssembler` 统一拼装，核心结构是：

1. **base prompt**
   - 来源：agent 自己绑定的 `prompt_ref`
   - 作用：定义角色、主任务、长期行为边界

2. **workspace_reminder**
   - 文件：`prompts/workspace_reminder.md`
   - XML 标记：`<system-reminder name="workspace_restrictions">`
   - 作用：强调 `/workspace` 是主要工作区，用户可见产物应优先落这里

3. **run_persistence_reminder**
   - 文件：`prompts/run_persistence_reminder.md`
   - XML 标记：`<system-reminder name="run_persistence">`
   - 作用：告诉模型每次都是一次独立 run，run 结束后内部临时上下文不会自动保留；跨 run 的事实要写进文件或其他持久化位置，并在阶段结束时主动总结

4. **admin_host_maintenance_reminder**（条件注入）
   - 文件：`prompts/admin_host_maintenance_reminder.md`
   - XML 标记：`<system-reminder name="admin_host_maintenance">`
   - 条件：当前是 frontstage + bot admin + host backend
   - 作用：告诉模型真实 skill 安装根在哪里、`/skills` 只是镜像视图、何时该用 `install_skill` / `refresh_extensions`

5. **tool_behavior_reminder**
   - 文件：`prompts/tool_behavior_reminder.md`
   - XML 标记：`<system-reminder name="tool_behavior">`
   - 作用：约束常见工具使用方式，尤其是 `message` 的行为红线

6. **skill_reminder**（条件注入）
   - 来源：运行时动态生成
   - 作用：列出当前 run 可见的 skills 摘要

7. **subagent_reminder**（条件注入）
   - 来源：运行时动态生成
   - 作用：列出当前 run 可见的 subagents 摘要

此外，还可能有部分 memory source 明确要求把内容注入到 `system_prompt` 槽位；这类内容不是静态 prompt 文件，但仍由 `ContextAssembler` 集中拼装。

## 新增 prompt 的推荐方式

1. 在 `prompts/` 下新增一个 `.md` 文件
2. 在 `assembler.py` 中增加对应 contribution builder
3. 如有动态变量，统一使用 `.format(...)` 或等价的明确格式化方式
4. 不要在业务代码里直接内联 system prompt 文案
5. 修改后同步更新本 README 里的“当前 system prompt 结构”，方便后来者快速理解整体拼装结果
