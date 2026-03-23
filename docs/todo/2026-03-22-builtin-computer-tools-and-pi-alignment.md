# 2026-03-22 builtin computer tools 和 pi 对齐 todo

现在要做的事情有两块，而且顺序不能反：

1. 先把 core tool 的注册方式改对，不再走 plugin。
2. 再把 computer 下面每个前台工具的行为改到和 pi 一样。

每次只写一个todo, 然后停下来汇报

每次都先查看pi的具体代码再动手

---

## 现在已经确认的判断

### 1. 现在的注册方式是错的

当前这些工具是通过 plugin 注册进 `ToolBroker` 

这会带来一个明显问题：

- plugin reload
- plugin disable
- plugin setup 失败

这些事情本来只该影响可选扩展，结果现在会连系统最基本的前台工具一起影响掉。这不对。

### 2. computer 工具行为现在也不对

最明显的问题：

- `read` 现在还是“只读 UTF-8 文本”
- 不能像 pi 一样读图片
- `edit` 还没补上
- shell 工具面也不像 pi

所以当前系统虽然有了 Work World 主线，但前台工具契约还没对齐。

---

## 最终目标

改完以后，系统应该长这样：

### 注册方式

- core tool 是 builtin tool，不是 plugin
- plugin 只表示外部可选扩展
- reload plugin 时，不会把 `read / write / edit / bash` 这些基础工具一起卸掉

### computer 工具面

前台模型看到的是稳定的一组基础工具，而不是 `computer` 这个名字：

- `read`
- `write`
- `edit`
- `bash`

这些工具都吃 Work World path：

- `/workspace/...`
- `/skills/...`
- `/self/...`

路径语义、可见性、backend 选择，都由上层先定好，再交给 `computer` 去执行。

---

## todo 1: 把 core tool 注册从 plugin 挪成 builtin tool

### 要新增的目录

新建 `builtin_tools` 目录，专门放系统自带工具的注册代码：

- `src/acabot/runtime/builtin_tools/__init__.py`
- `src/acabot/runtime/builtin_tools/computer.py`
- `src/acabot/runtime/builtin_tools/skills.py`
- `src/acabot/runtime/builtin_tools/subagents.py`

如果 `ask_backend` 也确认属于系统自带，再补：

- `src/acabot/runtime/builtin_tools/backend_bridge.py`

### 这层要做什么

这层只负责：

- 定义 tool spec
- 接住 tool call
- 把调用转给真正的 runtime service
- 直接注册到 `ToolBroker`

这层不负责：

- 管 workspace 生命周期
- 管 backend 生命周期
- 管 world path 真相
- 管 plugin 热加载

### 注册来源要改成稳定名字


- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`
- `builtin:backend_bridge`（如果保留）

### 要改的文件

- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/tool_broker/broker.py`
- `src/acabot/runtime/control/config_control_plane.py`
- `src/acabot/runtime/__init__.py`

### 这一步做完后的结果

- runtime 启动时，直接注册 builtin tool
- `RuntimePluginManager` 不再负责系统基础工具
- `replace_builtin_plugins(...)` 不再碰 core tool
- plugin reload 只影响真正的扩展插件

### 现在已经做完的内容

- 已经新建 builtin tool 注册目录：
  - `src/acabot/runtime/builtin_tools/__init__.py`
  - `src/acabot/runtime/builtin_tools/computer.py`
  - `src/acabot/runtime/builtin_tools/skills.py`
  - `src/acabot/runtime/builtin_tools/subagents.py`
- `build_runtime_components()` 启动时已经直接注册这些 builtin tool
- core tool 现在已经通过稳定来源进入 `ToolBroker`：
  - `builtin:computer`
  - `builtin:skills`
  - `builtin:subagents`
- 复用旧 `ToolBroker` 时，也会先清掉已经退役的旧 adapter source：
  - `plugin:computer_tool_adapter`
  - `plugin:skill_tool`
  - `plugin:subagent_delegation`
- `build_builtin_runtime_plugins()` 现在只保留真正还属于 plugin 的 `BackendBridgeToolPlugin()`
- `ToolBroker.register_tool()` 已经保护 builtin tool，不会让 plugin 用同名工具把它盖掉
- 可以注入 fresh 的 `RuntimePluginManager`, 但已经启动过的 manager 不再支持复用
- plugin reload、config reload 之后，builtin tool 仍然会留在 broker 里
- plugin 导入失败的路径现在会被单独记录，并通过 control plane 暴露出来，方便排查问题

---

## todo 2: 删除旧的 core tool plugin 适配层

在 `builtin_tools` 跑起来以后，直接删掉旧的 adapter/plugin。

### 要删除或下线的文件

- `src/acabot/runtime/plugins/computer_tool_adapter.py`
- `src/acabot/runtime/skills/tool_adapter.py`
- `src/acabot/runtime/plugins/subagent_delegation.py`

### 要同步清理的地方

- `src/acabot/runtime/plugins/__init__.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/__init__.py`
- 所有依赖 `build_builtin_runtime_plugins(...)` 的地方
- 所有把 core tool 当 plugin 的测试

### 这一步做完后的结果

- 系统里不再存在“builtin tools 伪装成 plugin”的双轨结构
- plugin 的含义重新变干净：就是外部扩展

### 现在已经做完的内容

- 旧的 core tool adapter 文件已经删除：
  - `src/acabot/runtime/plugins/computer_tool_adapter.py`
  - `src/acabot/runtime/skills/tool_adapter.py`
  - `src/acabot/runtime/plugins/subagent_delegation.py`
- 相关导出和装配已经同步清理：
  - `src/acabot/runtime/plugins/__init__.py`
  - `src/acabot/runtime/bootstrap/builders.py`
  - `src/acabot/runtime/__init__.py`
- 旧测试也已经一起清掉：
  - `tests/runtime/test_computer_tool_adapter.py`
  - `tests/runtime/test_skill_tool_plugin.py`
- 新的 builtin skill surface 测试已经补上：
  - `tests/runtime/test_builtin_skill_tools.py`
- 现在系统的基础前台工具已经由 builtin surface 承接，不再靠这些旧 adapter 文件接线
- 当前 `builtin:computer` 这层已经收成更小的表面，正在继续往 `read / write / edit / bash` 这个最终目标推进

---

## todo 3: 重做 computer 的对外工具接口

`computer` 不应该继续被理解成“文本文件 helper”。

它应该是 Work World 的基础执行层，真正对外支持：

- 文件读取
- 文件写入
- 文件编辑
- 跑 shell

### 要补的 runtime 接口

在 `src/acabot/runtime/computer/runtime.py` 里补齐真正的高层接口，给 `builtin_tools` 里的注册代码调用。

建议至少有：

- `read_world_path(...)`
- `write_world_path(...)`
- `edit_world_path(...)`
- `bash_world(...)`

名字可以再收，但语义必须清楚。

### backend 层只保留底层原语

`src/acabot/runtime/computer/backends.py` 只做“拿到真实路径后干活”。

要保留或补齐：

- `read_text(path)`
- `read_bytes(path)`
- `write_text(path, content)`
- shell/session 原语

backend 不做这些事情：

- world path 解析
- `/skills` `/self` 可见性判断
- `oldText` / `newText` 语义
- tool 文案拼接
- 图片结果封装

### 现在已经做完的内容

- `ComputerRuntime` 已经补上更清楚的一组入口：
  - `read_world_path(...)`
  - `write_world_path(...)`
  - `bash_world(...)`
- `ComputerRuntime` 现在自己持有 `skill_catalog`, builtin surface 不再替它保管这层依赖
- `src/acabot/runtime/computer/contracts.py` 里已经补上给前台工具用的返回值：
  - `WorldPathReadResult`
  - `WorldPathWriteResult`
- `src/acabot/runtime/builtin_tools/computer.py` 里的 `read` 和 `write` 已经改成调用这组新入口
- 现在 `/skills/...` 的镜像准备也已经收进 `ComputerRuntime` 入口里，不再由 builtin surface 先偷偷处理
- `/skills/...` 的读写现在也已经明确走 canonical skills 目录, 不再写进 `skill_views/...` 副本
- 这一步只整理了接口，没有提前开始图片 `read`、`edit` 和 `bash` 工具面的行为改造
- 相关测试已经补上并通过：
  - `tests/runtime/test_computer.py`
  - `tests/runtime/test_builtin_tools.py`

---

## todo 4: 把 `read` 改成和 pi 一样

这是最急的一项。

### 参数

`read` 的参数改成：

- `path`
- `offset` 可选
- `limit` 可选

### 文本文件行为

要支持：

- UTF-8 文本读取
- 分页
- `offset`
- `limit`
- 明确的截断提示

不要再只有一版简单全文读取。

### 图片文件行为

要支持：

- `jpg`
- `png`
- `gif`
- `webp`

要求：

- 不靠扩展名瞎猜
- 按真实内容判断 MIME
- tool result 返回图片 block
- 文本说明和图片一起返回

也就是说：

- `read("/workspace/a.png")` 应该成功返回图片
- 不是抛 `UnicodeDecodeError`

### 可能要新增的 helper

- `src/acabot/runtime/computer/media.py`
- 或者别的名字，只要目录清楚

这层负责：

- MIME 判断
- 图片结果封装
- 后续如果要做尺寸/大小保护，也放在这附近

### 现在已经做完的内容

- `read` 的工具参数已经补成：
  - `path`
  - `offset`
  - `limit`
- backend 已经补上 `read_bytes(path)`，所以现在不会再拿图片去硬按 UTF-8 打开
- 新增了两个 helper 文件：
  - `src/acabot/runtime/computer/media.py`
  - `src/acabot/runtime/computer/reading.py`
- `media.py` 现在已经能按文件字节识别：
  - `png`
  - `jpg`
  - `gif`
  - `webp`
- `read_world_path(...)` 现在已经会分两条路：
  - 普通文本按 `offset / limit` 读取，并给继续读取的提示
  - 图片文件返回说明文字和图片数据
- `/skills/...` 现在可以直接按可见 skill 读取, 不再要求先走 `mark_skill_loaded()` 这条预热链
- 不是支持图片、但又不是合法 UTF-8 的文件，现在会按 replacement decode 返回，不会直接抛 `UnicodeDecodeError`
- `builtin_tools/computer.py` 的 `read` 已经改成把这份结果直接交回去
- `read` 的工具说明现在也已经把分页契约直接写给模型看：
  - `2000 lines or 50KB`
  - `Use offset/limit for large files`
  - `continue with offset until complete`
- 这一步的测试已经补上并通过，覆盖了：
  - 文本分页
  - offset 越界
  - offset / limit 必须是正整数
  - 超长单行不会再假装有 `bash` 工具
  - png / jpg / gif / webp 图片读取
  - builtin `read` 参数暴露
- 这一步后面又根据 review 补修了四件事：
  - `reading.py` 不再给出假的 `Use bash:` 提示
  - `reading.py` 现在会拒绝 `offset <= 0` 和 `limit <= 0`
  - 文本末尾单独那个换行不会再被算成多出来的一行空行
  - 图片识别现在也有“后缀和真实字节不一致”这一类反例测试

---

## todo 5: 把 `write` 改到和 pi 一样

### 参数

- `path`
- `content`

### 行为

- 自动创建父目录
- 文件不存在就创建
- 已存在就覆盖
- 返回结果里写清楚写入了多少字节

不要再只返回一句很空的 `Wrote xxx`。

目标文案接近：

- `Successfully wrote 123 bytes to /workspace/foo.txt`

### 现在已经做完的内容

- `write_world_path(...)` 这层已经稳定返回：
  - `world_path`
  - `size_bytes`
- 当前 backend 的写文件逻辑已经被测试锁住：
  - 会自动创建父目录
  - 会覆盖已有文件
- `/skills/...` 的写入现在也已经走 canonical skills 目录：
  - 改已有文件不会再只改到 `skill_views/...` 副本
  - 新文件也能在可见 skill 目录里创建出来
- `builtin_tools/computer.py` 里的 `write` 工具说明已经改成 pi 这套说法：
  - 创建文件
  - 覆盖已有文件
  - 自动创建父目录
- `write` 成功后的返回文案已经改成：
  - `Successfully wrote {size} bytes to {path}`
- 这一步补过并跑通的测试包括：
  - `tests/runtime/test_computer.py`
  - `tests/runtime/test_builtin_tools.py`

---

## todo 6: 补上 `edit`，并直接按 pi 的样子做

### 参数名直接对齐 pi

- `path`
- `oldText`
- `newText`

不要再搞一套自己的 snake_case 工具参数。

### 行为要求

- 读整个文本文件
- 先精确匹配
- 找不到时报错
- 匹配到多个时报错
- 支持 `newText=""` 做删除
- 保留 BOM
- 保留原始换行风格
- 返回 diff 结果

### 最好一起补上的兼容行为

如果要真的和 pi 靠齐，建议同步补这套 fuzzy match：

- Unicode NFKC 归一化
- 智能引号转普通引号
- 各种 dash 归一化成 `-`
- 特殊空格归一化成普通空格
- 每行行尾空白处理

这不是必须第一步就做到 100%，但目标应该写清楚，不要只做半截 string replace。

### 建议新增 helper 文件

- `src/acabot/runtime/computer/editing.py`

让 `runtime.py` 不要塞满文字编辑细节。

### 现在已经做完的内容

- `builtin:computer` 现在已经注册了 `edit`
- `edit` 的工具参数已经对齐成 pi 这套名字:
  - `path`
  - `oldText`
  - `newText`
- `src/acabot/runtime/computer/editing.py` 已经新增, 专门处理这些文字替换细节:
  - BOM
  - 换行风格
  - 精确匹配
  - fuzzy 匹配
  - diff 生成
- `ComputerRuntime` 现在已经补上 `edit_world_path(...)`
- `src/acabot/runtime/computer/contracts.py` 里已经补上 `WorldPathEditResult`
- `src/acabot/runtime/builtin_tools/computer.py` 里的 `edit` 现在只做接线:
  - 取 `oldText / newText`
  - 调 `ComputerRuntime.edit_world_path(...)`
  - 返回 `Successfully replaced text in {path}.`
- `edit_world_path(...)` 现在已经能正确处理这些情况:
  - 单次替换成功
  - `newText=""` 删除文字
  - 找不到旧文本时报错
  - 旧文本出现多次时报错
  - 保留 UTF-8 BOM
  - 保留 CRLF 换行
  - 智能引号这类文字差异可以走 fuzzy 匹配
- 这一步补过并跑通的测试包括:
  - `PYTHONPATH=src pytest tests/runtime/test_builtin_tools.py -q -k 'edit or registers_core_tools_as_builtin_sources'`
  - `PYTHONPATH=src pytest tests/runtime/test_computer.py -q -k 'edit_world_path'`
  - `PYTHONPATH=src pytest tests/runtime/test_computer.py tests/runtime/test_builtin_tools.py tests/runtime/test_bootstrap.py tests/runtime/test_tool_broker.py -q`
  - 最后一条结果: `86 passed`

---

## todo 7: 不再提供 `ls` 和 `grep`

这次前台工具面直接收成四个：

- `read`
- `write`
- `edit`
- `bash`

所以：

- 不再单独注册 `ls`
- 不再单独注册 `grep`
- 目录探索交给 `bash`
- 文本搜索交给 `bash`

这一步做完以后，前台模型不再面对一堆重复工具，只保留最必要的一套基础工具。

---

### 现在已经做完的内容

- `builtin:computer` 这一层现在仍然只保留前台文件工具:
  - `read`
  - `write`
  - `edit`
- 这一步确认并锁住了一件事:
  - 就算 profile 里还残留写了 `ls` 或 `grep`, 也不会再把它们露给前台
- `src/acabot/runtime/computer/runtime.py` 里旧的前台残留入口已经删掉:
  - `list_world_entries(...)`
  - `grep_world(...)`
- `src/acabot/runtime/computer/contracts.py` 里的 backend 协议已经不再声明 `grep_text(...)`
- `src/acabot/runtime/computer/backends.py` 里旧的 `grep_text(...)` 实现也已经一起删掉
- 这一步补过并跑通的测试包括:
  - `PYTHONPATH=src pytest tests/runtime/test_computer.py tests/runtime/test_builtin_tools.py tests/runtime/test_bootstrap.py -q`
  - 结果: `77 passed`
- 这一步做完后, `ls / grep` 这条旧路已经从前台、runtime 入口、backend 协议三层一起收掉了
- 现在下一步应该做的是 **todo8**, 只盯 shell 工具面, 不要回头复活 `ls / grep`

---

## todo 8: 把 shell 工具面改成 pi 风格

这里不要再延续现在这套对模型暴露的接口：

- `exec`
- `bash_open`
- `bash_write`
- `bash_read`
- `bash_close`

### 目标

对前台模型统一暴露：

- `bash(command, timeout?)`

### 说明

内部如果还要继续用 session 机制实现，可以继续用。

但这些 session 细节不该继续直接暴露给模型。

### 这一步要做的事

- `builtin_tools/computer.py` 只注册 `bash`
- `ComputerRuntime` 内部自己决定是一把梭执行，还是复用现有 session 机制
- 旧的 `exec / bash_*` 工具从前台工具面移除

如果实现中发现这一步牵涉太大，可以先做兼容过渡，但最终目标不能变。

### 现在已经做完的内容

- `builtin:computer` 现在已经注册了 `bash`
- 前台 `bash` 的工具参数现在是:
  - `command`
  - `timeout`
- `src/acabot/runtime/builtin_tools/computer.py` 里的 `bash` 现在只做接线:
  - 取 `command / timeout`
  - 从工具上下文里拼当前命令要用的 computer policy
  - 调 `ComputerRuntime.bash_world(...)`
- `ComputerRuntime.bash_world(...)` 现在已经接收 `timeout`
- `ComputerRuntime.exec_once(...)` 现在也已经接收 `timeout`, 会继续把它传给 backend
- host / docker backend 的一次性命令执行现在都已经支持可选超时秒数
- `ComputerRuntime._available_tools(...)` 现在会在这些条件成立时把 `bash` 放进前台可用工具里:
  - 当前 world 看得到 `/workspace`
  - shell 真的能进当前 workspace
  - 当前 policy 允许跑命令
- 旧的前台 shell 工具没有回来:
  - `exec`
  - `bash_open`
  - `bash_write`
  - `bash_read`
  - `bash_close`
- 这一步补过并跑通的测试包括:
  - `PYTHONPATH=src pytest tests/runtime/test_builtin_tools.py tests/runtime/test_computer.py -q -k 'bash'`
  - 结果: `4 passed`
  - `PYTHONPATH=src pytest tests/runtime/test_computer.py tests/runtime/test_builtin_tools.py tests/runtime/test_bootstrap.py tests/runtime/test_tool_broker.py -q`
  - 结果: `89 passed`

---

## todo 9: 测试要先补，不要再先写实现再补洞

### 注册链测试

先补下面这些：

- core tool 来源是 `builtin:*`
- plugin reload 不影响 core tool
- config reload 后 core tool 还在
- 不再通过 `plugin:*` 注册 computer / skill / subagent 基础工具
- 前台 computer builtin tool 只剩 `read / write / edit / bash`

### computer 行为测试

#### `read`

- 读普通文本
- 读大文本分页
- `offset` 越界
- 读 png
- 读 jpg
- 读 gif
- 读 webp
- 读 `/workspace/attachments/...` 图片
- 读不可见 root 报错
- 对目录 target 明确报错，不再兼任 listing

#### `write`

- 自动建父目录
- 覆盖已有文件
- world path 正确

#### `edit`

- 单次替换成功
- 删除替换
- `oldText` 找不到
- 多次匹配报错
- CRLF 文件
- BOM 文件
- fuzzy match 场景

#### `bash`

- cwd 在当前 execution view
- 目录探索和文本搜索都通过 shell 完成
- host/docker 都按当前 world 工作
- subagent 看不到 `/self`

### 预计会动到的测试文件

- `tests/runtime/test_computer.py`
- `tests/runtime/test_tool_broker.py`
- `tests/runtime/test_bootstrap.py`
- `tests/runtime/test_control_plane.py`
- `tests/runtime/test_subagent_execution.py`

必要时新建：

- `tests/runtime/test_builtin_tools.py`

---

## todo 10: 文档最后要同步

这次不是只改代码。

至少要同步：

- `docs/00-ai-entry.md`
- `docs/12-computer.md`
- `docs/19-tool.md`
- `docs/HANDOFF.md`

### 这些文档要改什么

- core tool 和 plugin 的边界
- builtin tool 的注册方式
- computer 的职责
- 每个前台工具的最终形态
- shell 工具面

---

## 建议执行顺序

### 第 1 步
先改注册链：

- `builtin_tools` 建起来
- core tool 不再走 plugin

### 第 2 步
补 `read / write / edit`：

- 尤其是 `read` 图片支持
- `edit` 完整补齐

### 第 3 步
整理 `bash`，把目录探索和搜索彻底收回 shell

### 第 4 步
删掉旧 plugin adapter 残骸

### 第 5 步
跑测试、做 review、最后再同步文档

---

## 完成标准

这次改完，至少要满足下面这些结果：

- core tools 不再通过 plugin 注册
- plugin reload 不会影响基础工具
- 前台 computer builtin tool 只剩 `read / write / edit / bash`
- `read` 能读图片
- `edit` 可用，而且参数名就是 `oldText/newText`
- 前台默认 shell 工具面是 pi 风格
- 所有 file tool 都稳定吃 Work World path
- 测试覆盖注册链和工具行为
- 文档同步到最新状态

---

## 暂时不要做的事

- 不要再为旧 plugin adapter 续命
- 不要再给“文本版 read”找补丁式解释
- 不要为了旧 API 表面兼容继续保留双轨
- 不要把 backend maintainer、审计之类的话题混进这次任务主线

这次任务就盯两件事：

1. builtin tool 注册方式改正
2. computer 工具行为按 pi 对齐
