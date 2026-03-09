"""AcaBot 主入口 — 从 config.yaml 读取配置, 组装并启动所有组件.

组装顺序:
    Config → Gateway / Session / Store / Agent
    → Hook 注册 → Pipeline → BotContext
    → (async) Store 初始化 → Plugin 加载 → 启动 Gateway
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import signal
import sys
from typing import Any

from dotenv import load_dotenv

from .config import Config
from .gateway.base import BaseGateway
from .gateway.napcat import NapCatGateway
from .session.memory import InMemorySessionManager
from .agent.agent import LitellmAgent
from .hook import HookRegistry, ContextCompressorHook, MultimodalPreprocessHook
from .types import HookPoint
from .pipeline import Pipeline
from .plugin.context import BotContext
from .plugin.loader import PluginLoader
from .store.sqlite import SQLiteMessageStore

logger = logging.getLogger("acabot")


# region 组装

# 把组装逻辑提取为独立函数:
# 1. 可测试: 测试可以传入自定义 config, 检查组件是否正确配置
# 2. 可复用: 未来 App 类或其他入口可以复用这个函数
def build_components(config: Config) -> dict[str, Any]:
    """根据 config 实例化所有组件, 返回组件字典.

    同步函数, 只做实例化和接线. 需要异步初始化的组件(store/plugin)
    由调用方在 await 后完成, 见 _run().

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

    store_conf = config.get("store", {})
    store = SQLiteMessageStore(
        db_path=store_conf.get("db_path", "data/db/acabot.db"),
    )

    hooks = HookRegistry()
    _register_hooks(config, hooks, gateway)

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
        store=store,
    )

    bot = BotContext(
        gateway=gateway,
        session_mgr=session_mgr,
        agent=agent,
        config=config,
        store=store,
    )

    plugin_loader = PluginLoader()

    return {
        "config": config,
        "gateway": gateway,
        "session_mgr": session_mgr,
        "agent": agent,
        "store": store,
        "hooks": hooks,
        "pipeline": pipeline,
        "bot": bot,
        "plugin_loader": plugin_loader,
    }


def _register_hooks(
    config: Config,
    hooks: HookRegistry,
    gateway: BaseGateway,
) -> None:
    """从 config.hooks 读取配置, 创建并注册内置 hook.

    每个 hook 有独立的 enabled 开关, 默认 true.
    disabled 的 hook 不创建实例, 零开销.

    Args:
        config: 已加载的配置对象.
        hooks: HookRegistry 实例.
        gateway: Gateway 实例, MultimodalPreprocessHook 需要它来获取 reply 原文.
    """
    hooks_conf = config.get("hooks", {})

    # 内置 hook 始终创建并注册, enabled=false 时只设 hook.enabled=False.
    # HookRegistry.get() 会自动过滤 disabled 的 hook, 运行时可动态切换.

    # --- 多模态预处理 (on_receive, p=30) ---
    mm_conf = hooks_conf.get("multimodal", {})
    vision_model = mm_conf.get("vision_model", "") or None
    mm_hook = MultimodalPreprocessHook(
        vision_model=vision_model,
        gateway=gateway,
    )
    mm_hook.enabled = mm_conf.get("enabled", True)
    hooks.register(HookPoint.ON_RECEIVE, mm_hook)

    # --- 上下文压缩 (pre_llm, p=80) ---
    cc_conf = hooks_conf.get("context_compress", {})
    cc_hook = ContextCompressorHook(
        strategy=cc_conf.get("strategy", "truncate"),
        max_context_ratio=cc_conf.get("max_context_ratio", 0.7),
        preserve_recent=cc_conf.get("preserve_recent", 10),
    )
    cc_hook.enabled = cc_conf.get("enabled", True)
    hooks.register(HookPoint.PRE_LLM, cc_hook)


async def _load_plugins(components: dict[str, Any]) -> None:
    """加载外部插件.

    plugins 不在 src/ 的 package 内, 通过 sys.path 引入.
    后续 PluginLoader 支持目录扫描时替换此处手动 import.

    Args:
        components: build_components 返回的组件字典.
    """
    bot: BotContext = components["bot"]
    hooks: HookRegistry = components["hooks"]
    plugin_loader: PluginLoader = components["plugin_loader"]

    # plugins/ 在项目根目录, 用绝对路径避免依赖 cwd
    _project_root = pathlib.Path(__file__).resolve().parent.parent.parent
    plugins_dir = str(_project_root / "plugins")
    if plugins_dir not in sys.path:
        sys.path.insert(0, plugins_dir)

    try:
        from napcat_tools.plugin import NapCatToolsPlugin  # type: ignore[import-untyped]
        await plugin_loader.load_plugin(NapCatToolsPlugin(), bot, hooks)
    except ImportError:
        logger.warning("napcat_tools plugin not found, skipping")
    except Exception:
        logger.exception("Failed to load napcat_tools plugin")


# endregion


# region 日志


def setup_logging(config: Config) -> None:
    """配置日志级别和格式.

    config.logging.level 只控制 acabot 自身的日志级别.
    第三方库(litellm/websockets/openai)固定为 WARNING, 避免刷屏.

    Args:
        config: 已加载的配置对象.
    """
    log_conf = config.get("logging", {})
    level_name = log_conf.get("level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    # 全局 WARNING, acabot 命名空间按配置
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        force=True,
    )
    logging.getLogger("acabot").setLevel(level)


# endregion


# region 启动


async def _run() -> None:
    """异步主循环: 加载 .env → 加载配置 → 组装组件 → 异步初始化 → 启动 Gateway → 等待关闭."""
    # .env 必须在 Config 之前加载, litellm 从环境变量读 API Key
    load_dotenv()

    config = Config.from_file()
    setup_logging(config)

    components = build_components(config)
    gateway: NapCatGateway = components["gateway"]
    pipeline: Pipeline = components["pipeline"]
    store: SQLiteMessageStore = components["store"]
    plugin_loader: PluginLoader = components["plugin_loader"]

    # 异步初始化: store 建表/连接
    await store.initialize()
    logger.info(f"MessageStore initialized: {store.db_path}")

    # 加载插件
    await _load_plugins(components)

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

    # 优雅关闭: 逆序释放资源
    await plugin_loader.teardown_all()
    await gateway.stop()
    await store.close()
    logger.info("AcaBot stopped.")


def main() -> None:
    """同步入口, pyproject.toml [project.scripts] 指向此函数."""
    asyncio.run(_run())


# endregion


if __name__ == "__main__":
    main()
