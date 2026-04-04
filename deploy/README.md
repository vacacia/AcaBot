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
- `runtime_data/`（运行时数据目录。Compose 会把它同时挂到 `acabot` 和 `napcat` 容器里的 `/app/runtime_data`，用于共享 render 图片等本地发送产物）

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

## 注入测试事件

可以直接伪装成 NapCat 的反向 WS client, 往 `acabot` 容器的 `8080` 端口发一条 OneBot v11 事件:

```bash
python scripts/send_test_event.py --message-type private --user-id 10001 --text "测试一下"
```

默认会:
- 连接 `ws://127.0.0.1:8080`
- 带上当前 `deploy/napcat/config/onebot11_*.json` 里的 token
- 发送一条私聊 message event
- 等待 bot 回包, 把 `send_private_msg` 或 `send_group_msg` 打印出来

这个工具适合测 bot 的收消息、路由、agent 执行和出站动作. 它不会真的把消息发到 QQ, 因为回包会先被这个测试 client 接住。

## 主动发送通知

如果 `acabot` 和 `acabot-napcat` 已经连上，可以直接调用本地 WebUI API 主动发一条 bot 消息：

```bash
curl -X POST http://127.0.0.1:8765/api/notifications \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "qq:user:1733064202",
    "text": "AcaBot 主动通知测试"
  }'
```

`conversation_id` 目前使用 canonical 形式：
- 私聊: `qq:user:<qq号>`
- 群聊: `qq:group:<群号>`

这条接口会复用 runtime 自己的正式出站链路, 发送成功后也会写入 `MessageStore`。

## 本地文件发送 smoke 测试

当你想验证“workspace 本地文件 -> Outbox -> NapCat”这条链路有没有真的闭环，而又不想每次手上 QQ 客户端手测时，可以直接跑：

```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run python scripts/smoke_test_local_file_send.py \
  --conversation-id qq:user:10001 \
  --image x_screenshot.png
```

说明：
- 脚本会按目标 `conversation_id` 找到正式 workspace 根目录
- 如果没传 `--source-file`，会自动生成一个最小 PNG fixture
- 然后调用 `/api/notifications` 走正式发送链路
- 最后输出 API ack 和 `acabot-napcat` 日志摘要，并给出 `PASS` / `FAIL` / `SKIP/ENV-FAIL`

典型前置条件：
- `acabot` 容器在运行
- `acabot-napcat` 容器在运行
- WebUI API 可达（默认 `http://127.0.0.1:8765`）
