# skill 清理实现计划

> 不提交，只在当前工作区推进；每做完一段就更新 `docs/HANDOFF.md`。

## 目标

把 skill 从旧的 `skill_assignments + delegation` 结构，改成纯 `skills: list[str]`；把 subagent delegation 改成独立链路；skill 使用路径固定为方案 A。

## 原来是什么

- `AgentProfile.skill_assignments: list[SkillAssignment]`
- `SkillAssignment` 里有 `skill_name / delegation_mode / delegate_agent_id`
- `SubagentDelegationBroker` 支持 `skill_name -> assignment -> delegate_agent_id`
- `delegate_subagent` 同时接受 `skill_name` 和 `delegate_agent_id`
- control plane / WebUI / prompt 里也暴露这套旧语义

## 最后改成什么

- `AgentProfile.skills: list[str]`
- 删除 `SkillAssignment`
- 删除 `ResolvedSkillAssignment`
- `SkillCatalog` 只按 profile 的 skill 名列表解析可见 skill
- `SubagentDelegationBroker` 只按 `delegate_agent_id` 委派
- `delegate_subagent` 只接受 `delegate_agent_id + task + payload`
- skill 摘要继续进 prompt，skill 使用仍走现有 `skill(name=...)`
- 不再暴露任何 delegation_mode / delegate_agent_id 的 skill 字段

## 实施顺序

1. 先改测试，让核心行为表达成新口径。
2. 改 contracts / profile_loader / bootstrap，把 `skill_assignments` 改成 `skills`。
3. 改 skill catalog / control plane / tool broker，删掉 assignment 语义。
4. 改 subagent broker / plugin，只保留 direct delegation。
5. 改 config control plane / bot shell / session shell / UI 口径，把真源改成 `skills`。
6. 跑相关测试，修补断点。
7. 更新 `docs/HANDOFF.md` 记录已经删掉的旧结构和剩余尾巴。
