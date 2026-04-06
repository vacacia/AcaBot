# Pi sub2api 快速配置

下次给 pi 配 `sub2api / gpt-5.4` 时，直接按这几步做，不用再查资料。

## 1. 配 `~/.pi/agent/models.json`

写入自定义 provider：

```json
{
  "providers": {
    "sub2api": {
      "baseUrl": "https://vpsairobot.com",
      "api": "openai-responses",
      "apiKey": "你的 API key",
      "models": [
        {
          "id": "gpt-5.4",
          "name": "gpt-5.4",
          "reasoning": true,
          "input": ["text", "image"]
        }
      ]
    }
  }
}
```

## 2. 配 `~/.pi/agent/auth.json`

给这个 provider 单独放 key：

```json
{
  "sub2api": {
    "type": "api_key",
    "key": "你的 API key"
  }
}
```

## 3. 配 `~/.pi/agent/settings.json`

把默认模型切过去：

```json
{
  "defaultProvider": "sub2api",
  "defaultModel": "gpt-5.4",
  "defaultThinkingLevel": "high"
}
```

## 4. 验证

跑一条最小请求：

```bash
pi --provider sub2api --model gpt-5.4 --thinking minimal --no-session --no-tools -p "Reply with exactly OK."
```

看到返回 `OK` 就说明通了。

## 备注

- pi 看的是 `~/.pi/agent/*`，不是 `~/.codex/*`
- 自定义 provider 主要配 `models.json`
- 默认使用哪个模型看 `settings.json`
- 想看模型是否被识别，可用：

```bash
pi --provider sub2api --list-models gpt-5.4
```
