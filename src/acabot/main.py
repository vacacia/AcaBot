"""acabot.main 是新的启动入口.

组件关系:

    Config
      |
      v
    create_gateway / create_agent / create_message_store
      |
      v
    build_runtime_components()
      |
      v
    RuntimeApp.start()

这个文件只负责启动组装.
不再承担旧 `Session + Pipeline` 主线的业务职责.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable

from .agent import BaseAgent
from .config import Config
from .runtime import RuntimeComponents, build_runtime_components
from .runtime.gateway_protocol import GatewayProtocol
from .runtime.http_api import RuntimeHttpApiServer
from .runtime.stores import MessageStore

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs) -> None:
        _ = args, kwargs
        return None

logger = logging.getLogger("acabot")

GatewayFactory = Callable[[Config], GatewayProtocol]
AgentFactory = Callable[[Config], BaseAgent]
MessageStoreFactory = Callable[[Config], MessageStore | None]


# region factory
def create_gateway(config: Config) -> GatewayProtocol:
    """根据 Config 创建 Gateway.

    Args:
        config: 已加载的 Config 对象.

    Returns:
        一个满足 GatewayProtocol 的 gateway 实例.
    """

    gw_conf = config.get("gateway", {})

    # 延迟导入, 避免测试或纯 runtime 模块导入时拉起外部依赖.
    from .gateway.napcat import NapCatGateway

    return NapCatGateway(
        host=gw_conf.get("host", "0.0.0.0"),
        port=gw_conf.get("port", 8080),
        timeout=gw_conf.get("timeout", 10.0),
        token=gw_conf.get("token", ""),
    )


def create_agent(config: Config) -> BaseAgent:
    """根据 Config 创建默认 agent.

    Args:
        config: 已加载的 Config 对象.

    Returns:
        一个满足 `BaseAgent` 契约的 agent 实例.
    """

    agent_conf = config.get("agent", {})

    # 延迟导入, 避免 main 模块导入时强绑定具体 LLM 实现.
    from .agent.agent import LitellmAgent

    return LitellmAgent(
        max_tool_rounds=agent_conf.get("max_tool_rounds", 5),
    )


def create_message_store(config: Config) -> MessageStore | None:
    """根据 Config 创建 MessageStore override.

    默认返回 `None`, 让 `runtime.bootstrap` 按配置决定:
    - 配了 SQLite persistence 时, 自动组装 `SQLiteMessageStore`
    - 没配持久化时, 自动退回 `InMemoryMessageStore`

    Args:
        config: 已加载的 Config 对象.

    Returns:
        一个可选的 MessageStore override.
    """

    _ = config
    return None


# endregion


# region bootstrap
def build_runtime_app(
    config: Config,
    *,
    gateway_factory: GatewayFactory = create_gateway,
    agent_factory: AgentFactory = create_agent,
    message_store_factory: MessageStoreFactory = create_message_store,
) -> RuntimeComponents:
    """根据 Config 组装 RuntimeComponents.

    Args:
        config: 已加载的 Config 对象.
        gateway_factory: 创建 Gateway 的 factory.
        agent_factory: 创建默认 agent 的 factory.
        message_store_factory: 创建 MessageStore 的 factory.

    Returns:
        一份完整的 RuntimeComponents 组装结果.
    """

    gateway = gateway_factory(config)
    agent = agent_factory(config)
    message_store = message_store_factory(config)
    if message_store is None:
        return build_runtime_components(
            config,
            gateway=gateway,
            agent=agent,
        )

    return build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
        message_store=message_store,
    )


class ColorLogFormatter(logging.Formatter):
    """为终端日志增加轻量 ANSI 颜色."""

    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, *, use_color: bool) -> None:
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_color:
            return super().format(record)
        original_levelname = record.levelname
        color = self.LEVEL_COLORS.get(record.levelno, "")
        if color:
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class NoisyWebsocketHandshakeFilter(logging.Filter):
    """过滤探测 HTTP 口误打到 WS 端口的已知噪音."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "opening handshake failed" not in str(record.getMessage() or "")


def setup_logging(config: Config) -> None:
    log_conf = config.get("logging", {})
    level_name = log_conf.get("level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)
    use_color = bool(log_conf.get("color", True)) and not bool(os.getenv("NO_COLOR"))

    handler = logging.StreamHandler()
    handler.setFormatter(
        ColorLogFormatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            use_color=use_color,
        )
    )
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    logging.getLogger("acabot").setLevel(level)
    logging.getLogger("websockets.server").addFilter(NoisyWebsocketHandshakeFilter())


async def wait_for_shutdown_signal() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            continue
    await stop_event.wait()


async def _run() -> None:
    config = Config.from_file()
    try:
        load_dotenv(dotenv_path=config.base_dir() / ".env")
    except TypeError:
        load_dotenv()
    load_dotenv()
    setup_logging(config)
    components = build_runtime_app(config)
    webui_server = RuntimeHttpApiServer(
        config=config,
        control_plane=components.control_plane,
    )

    await components.app.start()
    await webui_server.start()
    logger.info("AcaBot runtime running. Press Ctrl+C to stop.")
    try:
        await wait_for_shutdown_signal()
    finally:
        await webui_server.stop()
        await components.app.stop()
        logger.info("AcaBot stopped.")


def main() -> None:
    asyncio.run(_run())


# endregion


if __name__ == "__main__":
    main()
