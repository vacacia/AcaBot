# progress.md

## 当前状态
- [x] 项目路径结构统一: filesystem-only，全 snake_case，三层分离（extensions/ / runtime_config/ / runtime_data/）
- [x] 文档清理完成: 删除 14 个冗余文档，合并记忆子系统文档，更新路径引用

## 最近变更
- `2026-03-27` 完成 lancedb-first long-term memory runtime
- `2026-03-29` ~ `2026-03-30` 系统页规划、session bundle source of truth、session-owned agent hard cut
- `2026-04-01` 优化 WebUI 与 long-term memory extraction / query planning
- `2026-04-02` 目录重构（deploy/、extensions/、runtime_config/、runtime_data/）
- `2026-04-02` 文档大清理：删除冗余文档，合并 17-* 到 05，更新 09 路径，更新 HANDOFF

## 已知问题
- webui 设计不完整，缺少很多配置页面
- 镜像太简陋（缺字体、python 环境、chrome 等）
- bot 掌握工具太少（文字转图片、查询数据库等）
- 日志过于简陋，重要信息显示不全面
- LTM 数据库安全性
- Reference Backend 不再需要且设计不合理需要删除

## 下一步
- WebUI 配置页面补全
- 工具扩展
- 镜像完善
