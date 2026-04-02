# progress.md

## 当前状态
- [x] 项目路径结构统一初步完成: 
    - 从 inline 到 filesystem 模式
    - 全 snake_case 命名
    - `extensions/` 统一收纳 plugins/skills/subagents
    - 三层真源分离：`extensions/` 是能力包目录, `runtime_config/` 是操作者真源, `runtime_data/` 是运行时事实 

## 最近变更
- `2026-03-27` 完成 lancedb-first long-term memory runtime
- `2026-03-29` 到 `2026-03-30` 已完成系统页规划、session bundle source of truth、session-owned agent hard cut
- `2026-04-01` 优化 WebUI 与 long-term memory extraction / query planning
- `2026-04-02` 已完成一轮目录重构，把部署、扩展、示例配置重新收束到更清晰的位置


## 已知问题
- 目录刚重构过，一些文档、示例路径、测试夹具和构建产物引用出现滞后
- 文档积攒过多, 需要压缩无用信息
- webui 设计不完整, 缺少很多配置
- 镜像太简陋, 没有基础的环境(字体, python环境, chrome..)
- bot掌握工具太少, 需要 文字转图片工具, 需要 查询数据库工具, 需要各种扩展提升能力
- 日志过于简陋, 重要信息显示不全面
- LTM 数据库安全性


## 下一步
- 更新系统地图、专题文档和 handoff，避免文档落后于代码

