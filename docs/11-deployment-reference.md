# 部署和运行环境说明

这一篇不讲发布流程，只讲现在项目实际怎么跑起来。

## 真实运行环境在哪

重点看 `runtime-env/`。

这个目录不是源码目录，而是运行实例目录。

里面通常有:

- `compose.yaml`
- `config.yaml`
- `.env`
- `runtime-config/`
- `runtime-data/`
- `napcat/`

## Docker Compose 结构

当前 `runtime-env/compose.yaml` 里主要有两个服务:

- `acabot`
- `napcat`

### `acabot`

职责:

- 跑 Python 主进程
- 暴露 gateway 监听端口
- 暴露 WebUI 端口

关键点:

- `ACABOT_CONFIG=/app/runtime-env/config.yaml`
- 会挂载 `runtime-config`、`runtime-data`
- 也会把仓库里的 `src` 和 `plugins` 挂进去

### `napcat`

职责:

- 提供 QQ / OneBot 侧接入

关键点:

- 挂载 NapCat 配置和登录态
- 通过网络连到 `acabot`

## NapCat 和 AcaBot 怎么接

当前是反向 WebSocket 模式。

也就是说:

- AcaBot 起一个 WS 服务端
- NapCat 主动连进来

对 AcaBot 来说，相关配置主要在 `gateway` 段。

对 NapCat 来说，要把反向 WS 地址指到 AcaBot 监听地址。

## 两种常见运行方式

### 1. 两边都在 compose 里

这时服务名互相可见，配置相对简单。

### 2. AcaBot 在宿主机，NapCat 在 Docker

这时地址配置最容易错。不要想当然地继续用 compose 内部服务名。

WebUI 里现在也专门有一些提示文案在提醒这件事。

## 本地直接运行

项目也支持不走 Docker 直接跑。

典型方式是:

`ACABOT_CONFIG=runtime-env/config.yaml PYTHONPATH=src python -m acabot.main`

这说明一件事:

真正的配置根目录通常是 `runtime-env/`，不是仓库根目录。

## 部署相关配置和业务配置要分开看

### 更偏部署态

- 端口
- token
- `.env`
- compose 挂载
- NapCat 连接方式

### 更偏业务态

- profiles
- prompts
- sessions
- computer
- runtime plugins
- model presets

如果你在做 WebUI 或配置管理，不要把这两类东西揉成一个概念。

## 运行时目录的实际意义

### `runtime-config/`

更像给 WebUI 和 runtime 热更新用的配置真源目录。

### `runtime-data/`

更像运行时状态和持久化数据目录，比如 SQLite、workspace 之类。

### `napcat/`

NapCat 自己的配置和登录态，不属于 AcaBot 业务配置。

## 部署相关改动时常见误区

### 1. 只改 Python 代码，不看 compose 和挂载

结果代码逻辑对了，运行环境根本不给你这个文件或目录。

### 2. 只改 WebUI 提示，不改真实配置路径

结果页面上说得很对，实际进程根本没读到那份配置。

### 3. 默认根目录 config.yaml 就是权威配置

很多时候不是。真正跑起来的实例通常读的是 `runtime-env/config.yaml`。

## 读文件顺序建议

1. `runtime-env/README.md`
2. `runtime-env/compose.yaml`
3. `src/acabot/config.py`
4. `src/acabot/main.py`
5. `src/acabot/gateway/napcat.py`
