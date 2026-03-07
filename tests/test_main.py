"""main.py 测试 — 验证 build_components 配置传递 + 边界行为."""

from __future__ import annotations

from acabot.config import Config
from acabot.main import build_components
from acabot.gateway.napcat import NapCatGateway
from acabot.agent.agent import LitellmAgent


# region 配置传递


class TestBuildComponentsConfigPassthrough:
    """config 的值能正确传递到各组件(不测默认值, 只测传递链路)."""

    def setup_method(self):
        self.config = Config({
            "gateway": {"host": "127.0.0.1", "port": 9090, "timeout": 30.0},
            "agent": {
                "default_model": "claude-3-haiku",
                "max_tool_rounds": 10,
                "system_prompt": "你是测试机器人",
            },
            "session": {"max_messages": 50},
            "pipeline": {"error_reply": "系统繁忙"},
        })
        self.components = build_components(self.config)

    def test_gateway_receives_config(self):
        gw = self.components["gateway"]
        assert gw.host == "127.0.0.1"
        assert gw.port == 9090
        assert gw.timeout == 30.0

    def test_agent_receives_config(self):
        agent = self.components["agent"]
        assert agent.default_model == "claude-3-haiku"
        assert agent.max_tool_rounds == 10

    def test_session_receives_config(self):
        assert self.components["session_mgr"].max_messages == 50

    def test_pipeline_receives_config(self):
        p = self.components["pipeline"]
        assert p.error_reply == "系统繁忙"
        assert p.system_prompt == "你是测试机器人"

    def test_empty_config_does_not_crash(self):
        """空配置不会报错(各组件有自己的默认值)."""
        components = build_components(Config({}))
        assert isinstance(components["gateway"], NapCatGateway)
        assert isinstance(components["agent"], LitellmAgent)


# endregion


# region error_reply 边界


class TestErrorReplyConfig:
    """error_reply 的 falsy 值处理 — 这是 main.py 自己的逻辑, 值得测."""

    def test_empty_string_means_no_reply(self):
        """空字符串 → None(不回复)."""
        config = Config({"pipeline": {"error_reply": ""}})
        components = build_components(config)
        assert components["pipeline"].error_reply is None

    def test_null_means_no_reply(self):
        """yaml 里写 null → Python None → 不回复."""
        config = Config({"pipeline": {"error_reply": None}})
        components = build_components(config)
        assert components["pipeline"].error_reply is None

    def test_custom_reply(self):
        config = Config({"pipeline": {"error_reply": "哎呀出错了"}})
        components = build_components(config)
        assert components["pipeline"].error_reply == "哎呀出错了"


# endregion
