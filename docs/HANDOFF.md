# 当前进展 Handoff

## 2026-03-22 builtin computer tools 和 pi 对齐已经收口

这轮最重要的结果已经稳定下来：

- core tool 已经不再靠 plugin 生命周期注册
- 前台 `computer` 工具面现在已经固定成：
  - `read`
  - `write`
  - `edit`
  - `bash`
- 前台已经不再暴露这些旧工具：
  - `ls`
  - `grep`
  - `exec`
  - `bash_open`
  - `bash_write`
  - `bash_read`
  - `bash_close`

## builtin tool 和 plugin 的边界

现在真正直接注册进 `ToolBroker` 的基础工具来源是：

- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`

`plugin` 现在主要表示外部扩展能力。
前台基础工具已经从 plugin 生命周期里拆出来了，所以 plugin reload 不会再把 `read / write / edit / bash` 一起带坏。

## computer 当前真相

现在真正干活的是：

- `src/acabot/runtime/computer/runtime.py`

前台 builtin surface 只是接线层：

- `src/acabot/runtime/builtin_tools/computer.py`

`ComputerRuntime` 现在已经有这组稳定入口：

- `read_world_path(...)`
- `write_world_path(...)`
- `edit_world_path(...)`
- `bash_world(...)`

其中：

- `read` 支持 `path / offset / limit`，文本分页，图片读取
- `write` 支持自动建父目录、覆盖写入、返回字节数
- `edit` 支持 `path / oldText / newText`，BOM、CRLF、fuzzy match、diff
- `bash` 支持 `command / timeout`

## `/skills/...` 现在的规则

这块这轮也已经收清楚了：

- `/skills/...` 的读写已经走 canonical skills 目录
- 不再写进 `skill_views/...` 副本
- 可见 skill 可以直接被 `read` 访问
- builtin surface 不再自己偷偷做 skill mirror 预处理
- 这些事情已经收回 `ComputerRuntime` 里处理

## `edit` 和 pi 当前版本的对齐点

收尾 review 里最容易争起来的是 `edit` 的 fuzzy 行为。
这轮已经重新核对过 pi 当前真正生效的版本：

- `@mariozechner/pi-coding-agent/dist/core/tools/edit.js`
- `@mariozechner/pi-coding-agent/dist/core/tools/edit-diff.js`

结论是：

- fuzzy 命中后，pi 当前版本确实会拿归一化后的整份文字做替换基底
- `Found N occurrences` 这一步，pi 当前版本也确实一直按 fuzzy 归一化后的文字计数

AcaBot 现在和 **pi 当前版本** 保持一致。
不要再被旧的 `packages/mom/src/tools/edit.ts` 带偏。

## 测试验证

这轮最后跑过的完整验证是：

- `PYTHONPATH=src pytest tests/runtime tests/test_main.py tests/test_config_example.py -q`
- 结果：`352 passed`

另外，`edit` 那两个最容易误判的 fuzzy 行为也单独重新跑过：

- `PYTHONPATH=src pytest tests/runtime/test_computer.py -q -k 'fuzzy_match_normalizes_other_lines_like_pi or exact_match_still_rejects_fuzzy_duplicates_like_pi'`
- 结果：`2 passed`

## 文档状态

这轮和当前代码对齐的文档主要是：

- `docs/06-tools-plugins-and-subagents.md`
- `docs/12-computer.md`
- `docs/todo/2026-03-22-builtin-computer-tools-and-pi-alignment.md`
- `docs/HANDOFF.md`

## 如果后面继续看这块，先看哪里

建议按这个顺序：

1. `docs/12-computer.md`
2. `docs/06-tools-plugins-and-subagents.md`
3. `src/acabot/runtime/computer/runtime.py`
4. `src/acabot/runtime/builtin_tools/computer.py`
5. `tests/runtime/test_computer.py`
6. `tests/runtime/test_builtin_tools.py`

## 当前收尾状态

这轮 builtin computer tools 和 pi 对齐，已经可以按完成处理。
接下来如果还继续动，就不是补主线缺口了，而是继续打磨或扩能力。