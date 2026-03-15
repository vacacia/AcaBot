# Runtime Env

这个目录只放运行环境，不放源代码。

包含内容:

- `compose.yaml`: Docker 部署入口
- `config.yaml`: 当前实例使用的主配置
- `.env`: 当前实例使用的环境变量
- `runtime-config/`: WebUI 可写的 profiles / prompts / rules / models
- `runtime-data/`: SQLite、workspace 等运行数据
- `napcat/`: NapCat 配置和登录态

常用命令:

```bash
cd runtime-env
docker compose up -d --build
docker compose logs -f acabot
```

本地直接运行:

```bash
cd /path/to/AcaBot
ACABOT_CONFIG=runtime-env/config.yaml PYTHONPATH=src python -m acabot.main
```
