# 13. System Prompt 组成与位置

这份文档只回答两件事：

1. 当前发给模型的 system prompt 由哪些部分组成
2. 以后如果想改 system prompt，去哪里找

先记一个当前约定：

- **工具描述** 解决“怎么用”
- **系统提示词** 解决“选哪个”

## 最终 system prompt 是怎么组成的

最终 system prompt 不是单一文件，而是运行时组装出来的。

当前组成如下：

1. **Base prompt**
   - 来源：当前 agent 的 `prompt_ref`
   - 典型文件位置：`runtime_config/prompts/*.md`
   - 加载入口：`src/acabot/runtime/control/prompt_loader.py`

2. **稳定注入的 workspace reminder**
   - 内容：`所有工作都在 /workspace 中完成。`
   - 位置：`src/acabot/runtime/context_assembly/assembler.py`

3. **稳定注入的工具选择 / 行为提醒**
   - 这层解决“什么时候该选 `message` 工具”
   - 内容类型：
     - 普通纯文本回复可以直接正常回答
     - 想发送图片、想在一条消息里附带 `@` / 引用、或想把回答内容用 Markdown / LaTeX 渲染后再发送时，选择 `message` 工具
     - 调用工具前先做一句简短说明
     - 工具失败后不要静默结束，要解释并继续处理
   - 位置：`src/acabot/runtime/context_assembly/assembler.py`

4. **可见 skills / subagents 摘要**
   - 位置：`src/acabot/runtime/context_assembly/assembler.py`

5. **显式声明要进入 system prompt 的 memory blocks**
   - 也是由 assembler 合并
   - 位置：`src/acabot/runtime/context_assembly/assembler.py`

## 运行时主链路位置

如果你想顺着代码看最终 system prompt 是怎么到模型那边的，按这个顺序找：

1. `src/acabot/runtime/model/model_agent_runtime.py`
   - `prompt_loader.load(ctx.agent.prompt_ref)` 读取 base prompt
   - `context_assembler.assemble(...)` 组装最终 system prompt
   - `ctx.system_prompt` 最终传给底层 agent

2. `src/acabot/runtime/context_assembly/assembler.py`
   - 定义 system prompt 额外注入项
   - 定义组装顺序和优先级

3. `src/acabot/runtime/control/prompt_loader.py`
   - 定义 `prompt_ref -> prompt 文件` 的加载方式

## prompt 文件真源在哪里

默认 filesystem 真源下，prompt 文件通常在：

- `runtime_config/prompts/default.md`
- `runtime_config/prompts/aca.md`

agent 具体使用哪个 prompt，由 session/agent 配置决定，例如：

- `runtime_config/sessions/<platform>/<scope>/<id>/agent.yaml`

这里的 `prompt_ref` 决定会加载哪个 prompt 文件。

## 哪些东西**不是** system prompt

下面这些会影响模型行为，但它们不属于 system prompt：

1. **工具 schema / 工具 description**
   - 这层解决“工具参数怎么填、怎么调用”
   - 例如 `message` 工具的发送规则
   - 位置：`src/acabot/runtime/builtin_tools/message.py`

2. **人格设定 prompt 文件本身以外的运行时提醒**
   - 人格 prompt 只放人格相关内容
   - 不建议把工具行为、发送契约、workspace 契约直接混进人格 prompt

## 以后如果想改 system prompt，优先看哪里

### 改人格 / 语气 / 常驻身份
看：
- `runtime_config/prompts/*.md`

### 改稳定注入的系统提醒
看：
- `src/acabot/runtime/context_assembly/assembler.py`

### 改 prompt 文件加载逻辑
看：
- `src/acabot/runtime/control/prompt_loader.py`

### 改工具使用规则本身
看：
- 对应 builtin tool 文件，例如：`src/acabot/runtime/builtin_tools/message.py`

## 当前约定

- **人格 prompt** 和 **工具/执行约束** 分开维护
- 工具行为提醒放在 `ContextAssembler`
- 工具发送契约放在具体工具 schema
- 不把冗长原理塞进 system prompt
