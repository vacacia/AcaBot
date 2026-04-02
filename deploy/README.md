# AcaBot 部署说明

## 生产模式

```bash
cd deploy
cp .env.example .env        # 修改端口等 Compose 变量
docker compose up -d --build
```

根目录需准备：
- `config.yaml`（从 `config.example.yaml` 复制）
- `.env`（从 `.env.example` 复制，填入 API key）
- `runtime_config/`（从 `runtime_config.example/` 复制）

## 开发模式

```bash
cd deploy
docker compose -f compose.yaml -f compose.dev.yaml up
```

开发 override 会挂载 `src/` 和 `webui/` 到容器内。

## 本地运行（不用 Docker）

```bash
python -m acabot.main
```
