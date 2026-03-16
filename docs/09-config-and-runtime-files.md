# 配置、运行时文件和生效路径

这一篇主要解决两个问题:

1. 配置到底从哪里来
2. 改完之后什么时候生效

## `Config` 是最底层入口

在 `src/acabot/config.py`。

它很简单，但很关键。

主要能力:

- `from_file()`
- `get()`
- `save()`
- `reload_from_file()`
- `base_dir()`
- `resolve_path()`

### 配置文件查找顺序

`Config.from_file()` 的优先级是:

1. 显式传入 path
2. 环境变量 `ACABOT_CONFIG`
3. 默认 `config.yaml`

### 一个现实情况

仓库根目录当前不一定真的有可用的 `config.yaml`。实际部署更像是走 `runtime-env/config.yaml`，再通过 `ACABOT_CONFIG` 指过去。

所以你改配置逻辑时，不要默认“项目根下就有一份权威 config.yaml”。

## 运行时配置不只一份 YAML

现在系统支持两类来源:

### 1. 主配置

主要由 `Config` 读取。

内容通常包括:

- gateway
- agent
- runtime
- plugins

### 2. 文件系统配置目录

如果开启 `runtime.filesystem.enabled`，运行时还会从文件系统目录加载:

- profiles
- prompts
- bindings
- inbound rules
- event policies
- models 等

相关代码重点看:

- `runtime/control/profile_loader.py`
- `runtime/control/config_control_plane.py`

## 为什么这点重要

因为很多 WebUI 页面改的不是主 YAML 某一段，而是运行时目录下的一组文件。

你如果只改 `Config`，往往只改对了一半。

## 哪些配置会影响哪些模块

### `gateway`

影响:

- `main.py` 创建 `NapCatGateway`
- WebUI 的 gateway 状态页
- 部署接线

### `agent`

影响:

- 默认 agent 创建
- 默认模型
- 默认系统 prompt

### `runtime`

影响最大，通常包括:

- default agent/profile
- profiles
- filesystem 模式
- webui
- computer
- plugins
- binding rules
- inbound rules
- event policies

这里还有一个现在很容易被忽略的点:

- 事件规则不再只看 `targets_self`
- 还可以继续细分成 `mentions_self` 和 `reply_targets_self`

也就是说, “明确 @ 了 bot”, “是在回 bot 的消息”, “只是群里路过消息” 现在已经是三类不同的输入事实, 不需要全都挤进一个 `targets_self` 布尔值里。

WebUI 的 bot 事件默认面板也已经按这个思路细分了 `message`:

- `消息 @bot`
- `消息 引用bot`
- `消息 普通群聊`
- `消息 其他`

所以如果你改的是这块面板, 不要再假设“message 只有一行默认行为”。

### profile 配置里现在已经有图片理解块

这类配置不放 `runtime.plugins`，而是跟 agent / session AI 配置一起走。

当前实现里，profile 或 session managed profile 可以带:

- `image_caption.enabled`
- `image_caption.caption_preset_id`
- `image_caption.caption_prompt`
- `image_caption.include_reply_images`

这说明图片理解现在属于“当前 agent 如何理解消息”的一部分，不是独立 plugin 私有配置。

更具体一点说:

- 这组配置控制的是“消息整理阶段”怎样处理图片
- 不是工具开关
- 也不是 memory 策略开关

### `plugins`

影响 plugin 的加载和插件私有配置。

## 热刷新 vs 需要重启

不要假设所有配置都能热刷新。

建议按这两类来理解:

### 更可能热刷新的

- profiles
- prompts
- binding rules
- inbound rules
- event policies
- 部分 plugin 配置

像 `image_caption.*` 这种 profile / session AI 字段，也属于这一类。

### 更可能需要重启的

- gateway 监听地址 / token
- 进程级环境变量
- Docker / NapCat 接线
- 某些基础设施初始化参数

如果你做 WebUI 配置页，最好在页面文案里把这点说清楚。

## `runtime-env/` 是干什么的

这个目录更像“实际运行实例的工作目录”，不是源代码目录。

里面通常会放:

- `compose.yaml`
- `config.yaml`
- `.env`
- `runtime-config/`
- `runtime-data/`
- `napcat/`

对于部署和实际运行来说，这个目录比仓库根目录更接近真实现场。

## 路径解析规则

`Config.resolve_path()` 会把相对路径解析到当前配置文件所在目录。

这点很重要，因为:

- 同样写 `profiles/`
- 在项目根 config 和在 `runtime-env/config.yaml` 下，实际指向的目录不是一个地方

所以你如果改 filesystem 目录、workspace、模型目录等路径，别只盯字符串，要看配置文件所在目录。

## 设计新配置项时的建议

### 1. 先决定归属层级

放哪一段:

- `gateway`
- `agent`
- `runtime`
- `plugins.<plugin_name>`

不要随手塞。

### 2. 想清楚是不是“运行时可改”

如果以后要给 WebUI 改，最好从一开始就想好:

- 是否能热刷新
- 改完是否需要同步 reload 某个注册表

### 3. 想清楚是不是“部署态配置”

像 token、端口、挂载路径这类，更偏部署态。不要和纯业务配置混着讲。

## AI 在改配置相关代码前要先确认的事

1. 当前实例到底读的是哪份 config
2. 是否开启了 filesystem 模式
3. 目标改动是运行时配置还是部署配置
4. 改完要不要热刷新
5. WebUI 是否也要同步暴露
