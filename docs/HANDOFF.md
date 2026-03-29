# 当前进展 Handoff

subagent 定义真源已经从 profile / plugin 方向收成文件系统 catalog，每个 subagent 只认自己的 `SUBAGENT.md`，plugin 和 subagent 的直接注册关系已经删除。
session 现在只负责 `visible_subagents`，`delegate_subagent` 只有在当前 run allowlist 非空且 catalog 能解析时才会暴露，control plane / HTTP API / WebUI / ops 也都改成展示 catalog subagent。
第一版 subagent child run 默认不递归，也不支持 approval resume；一旦命中需要审批的工具会直接失败，所以继续往后做时不要把它当成可恢复的子会话。
