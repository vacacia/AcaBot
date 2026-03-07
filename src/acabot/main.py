"""AcaBot 主入口 — 从 config.yaml 读取配置, 组装并启动所有组件.

组装顺序:
    Config → Gateway / Session / Agent → Pipeline → BotContext → (Plugins) → 启动
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from dotenv import load_dotenv

from .config import Config
from .gateway.napcat import NapCatGateway
from .session.memory import InMemorySessionManager
from .agent.agent import LitellmAgent
from .hook import HookRegistry
from .pipeline import Pipeline
from .plugin.context import BotContext
from .store.null import NullMessageStore

logger = logging.getLogger("acabot")


# region 组装

# 把组装逻辑提取为独立函数:
# 1. 可测试: 测试可以传入自定义 config, 检查组件是否正确配置
# 2. 可复用: 未来 App 类或其他入口可以复用这个函数
def build_components(config: Config) -> dict[str, Any]:
    """根据 config 实例化所有组件, 返回组件字典.

    Args:
        config: 已加载的配置对象.

    Returns:
        包含所有组件的字典, key 为组件名.
    """
    gw_conf = config.get("gateway", {})
    agent_conf = config.get("agent", {})
    session_conf = config.get("session", {})
    pipeline_conf = config.get("pipeline", {})

    gateway = NapCatGateway(
        host=gw_conf.get("host", "0.0.0.0"),
        port=gw_conf.get("port", 8080),
        timeout=gw_conf.get("timeout", 10.0),
    )

    session_mgr = InMemorySessionManager(
        max_messages=session_conf.get("max_messages", 20),
    )

    agent = LitellmAgent(
        default_model=agent_conf.get("default_model", "gpt-4o-mini"),
        max_tool_rounds=agent_conf.get("max_tool_rounds", 5),
    )

    hooks = HookRegistry()

    # error_reply: 字符串则发送该文案, 空字符串/null 则不回复
    raw_error_reply = pipeline_conf.get("error_reply", "出了点问题, 请稍后再试")
    error_reply = raw_error_reply if raw_error_reply else None

    pipeline = Pipeline(
        gateway=gateway,
        agent=agent,
        system_prompt=agent_conf.get("system_prompt", ""),
        session_mgr=session_mgr,
        hooks=hooks,
        error_reply=error_reply,
    )

    bot = BotContext(
        gateway=gateway,
        session_mgr=session_mgr,
        agent=agent,
        config=config,
        store=NullMessageStore(),
    )

    return {
        "config": config,
        "gateway": gateway,
        "session_mgr": session_mgr,
        "agent": agent,
        "hooks": hooks,
        "pipeline": pipeline,
        "bot": bot,
    }


# endregion


# region 日志


def setup_logging(config: Config) -> None:
    """配置日志级别和格式.

    Args:
        config: 已加载的配置对象.
    """
    log_conf = config.get("logging", {})
    level_name = log_conf.get("level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        force=True,
    )


# endregion


# region 启动


async def _run() -> None:
    """异步主循环: 加载 .env → 加载配置 → 组装组件 → 启动 Gateway → 等待关闭."""
    # .env 必须在 Config 之前加载, litellm 从环境变量读 API Key
    load_dotenv()

    config = Config.from_file()
    setup_logging(config)

    components = build_components(config)
    gateway: NapCatGateway = components["gateway"]
    pipeline: Pipeline = components["pipeline"]

    # 接通消息流: Gateway 收到事件 → Pipeline.process
    gateway.on_event(pipeline.process)

    await gateway.start()
    logger.info("AcaBot running. Press Ctrl+C to stop.")

    # 等待关闭信号
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()

    await gateway.stop()
    logger.info("AcaBot stopped.")


def main() -> None:
    """同步入口, pyproject.toml [project.scripts] 指向此函数."""
    asyncio.run(_run())


# endregion


if __name__ == "__main__":
    main()
