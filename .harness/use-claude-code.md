## 用法

```bash
claude -p --dangerously-skip-permissions --tools <TOOLS> --output-format text --model opus --effort high "<PROMPT>"
```
- `-p`：非交互输出
- `--dangerously-skip-permissions`：跳过权限确认
- `--output-format text`：直接输出文本结果
- model只允许选opus, effort只允许选high
- 超时时间设置 1200s

TOOLS 可选:
- `Read`
- `Bash`
- `Read,Bash`

## 原则

- Claude review 只是**补充视角**，不是替代本地验证
- Claude 的意见要**自己判断**，不要盲从


