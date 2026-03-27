# 当前进展 Handoff

phase 1 的 `Model Target Registry Backend Unification` 已经落地：正式模型真源现在是 `model_provider / model_preset / model_target / model_binding`，runtime 消费侧只按 target 解析模型，`AgentProfile.default_model` 和 Session 私有模型字段已经退出主线，Session WebUI 也改成了明确占位页。  
这一轮把 target/binding 的硬边界补全了：plugin slot revalidate 失败会回滚 target，删除 profile 前会阻断仍有 `agent:*` binding 的对象，`/api/ui/catalog` 会返回 `ModelBindingSnapshot`，而 `model_preset` 的正式契约已经从单选 `capability` 收成 `task_kind + capabilities`，`system:image_caption` 也会校验 `image_input`。  
当前本地验收继续按“跳过 backend/pi/真实 LLM 套件”执行，命令是 `PYTHONPATH=src pytest $(find tests/runtime -name 'test_*.py' ! -path '*/backend/*' ! -name 'test_backend_routing.py' ! -name 'test_tool_broker_backend_bridge.py' ! -path '*/control/test_backend_http_api.py') tests/test_main.py -q`，结果是 `434 passed in 25.21s`；phase 1 之后的下一步就是在这个基线上实现 `long_term_memory` 第一版。
