# NapCatToolsPlugin: tool handler + 配置过滤 + attachment 协议
# Agent attachment 提取: _execute_tool 分离 attachments
# Pipeline image segment: URL 用 file 字段, base64 加前缀

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from acabot.agent.agent import LitellmAgent
from acabot.agent.response import AgentResponse, Attachment
from acabot.pipeline import Pipeline
from acabot.session.memory import InMemorySessionManager
from acabot.types import StandardEvent, EventSource, MsgSegment, ActionType
from acabot.config import Config
from acabot.plugin.context import BotContext
from napcat_tools.plugin import NapCatToolsPlugin


# region NapCatToolsPlugin

def _make_bot(gateway=None, config_data=None, agent=None):
    """构造带 mock gateway 的 BotContext."""
    gw = gateway or AsyncMock()
    return BotContext(
        gateway=gw,
        session_mgr=AsyncMock(),
        agent=agent or MagicMock(),
        config=Config(config_data or {}),
    )


class TestNapCatToolsPlugin:
    """NapCatToolsPlugin: tool handler 返回格式, API 错误处理, 头像 URL 拼接."""

    @pytest.fixture
    async def plugin(self):
        """setup 好的插件实例, gateway.call_api 默认返回成功."""
        gw = AsyncMock()
        gw.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {"user_id": 12345, "nickname": "TestUser"},
        })
        bot = _make_bot(gateway=gw)
        p = NapCatToolsPlugin()
        await p.setup(bot)
        return p

    async def test_get_user_info_returns_avatar_url(self, plugin):
        tools = plugin.tools()
        get_user = next(t for t in tools if t.name == "get_user_info")
        result = await get_user.handler({"user_id": 12345})

        assert result["nickname"] == "TestUser"
        assert "12345" in result["avatar_url"]
        # 没配 vision_model, 不应有 avatar_description
        assert "avatar_description" not in result
        assert "images_for_llm" not in result
        assert "attachments" not in result

    async def test_get_user_info_prefers_api_avatar(self, plugin):
        # API 返回了 avatar_url → 优先使用, 不拼接 qlogo
        plugin._gateway.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {
                "user_id": 12345,
                "nickname": "TestUser",
                "avatar_url": "https://napcat-returned-avatar.com/real.jpg",
            },
        })
        tools = plugin.tools()
        get_user = next(t for t in tools if t.name == "get_user_info")
        result = await get_user.handler({"user_id": 12345})

        assert result["avatar_url"] == "https://napcat-returned-avatar.com/real.jpg"
        assert "qlogo" not in result["avatar_url"]

    async def test_get_user_info_api_failure(self, plugin):
        # API 返回失败 → _call_api 抛 RuntimeError → _execute_tool 捕获返回 error
        plugin._gateway.call_api = AsyncMock(return_value={
            "status": "failed", "msg": "user not found",
        })
        tools = plugin.tools()
        get_user = next(t for t in tools if t.name == "get_user_info")
        with pytest.raises(RuntimeError, match="user not found"):
            await get_user.handler({"user_id": 99999})

    async def test_get_group_info(self, plugin):
        plugin._gateway.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {"group_id": 100, "group_name": "TestGroup", "member_count": 42},
        })
        tools = plugin.tools()
        get_group = next(t for t in tools if t.name == "get_group_info")
        result = await get_group.handler({"group_id": 100})

        assert result["group_name"] == "TestGroup"
        assert result["member_count"] == 42

    async def test_get_group_member_info_returns_avatar_url(self, plugin):
        # get_group_member_info 应返回 avatar_url, 无 vision_model 不做识图
        plugin._gateway.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {"user_id": 12345, "nickname": "TestUser", "card": "TestCard", "role": "member"},
        })
        tools = plugin.tools()
        get_member = next(t for t in tools if t.name == "get_group_member_info")
        result = await get_member.handler({"group_id": 100, "user_id": 12345})

        assert "12345" in result["avatar_url"]
        assert "avatar_description" not in result
        assert "images_for_llm" not in result
        assert "attachments" not in result

    async def test_get_group_member_list_wraps_in_members_key(self, plugin):
        # member_list 返回的 data 是 list, handler 应包成 {"members": [...]}
        plugin._gateway.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": [{"user_id": 1, "nickname": "A"}, {"user_id": 2, "nickname": "B"}],
        })
        tools = plugin.tools()
        get_members = next(t for t in tools if t.name == "get_group_member_list")
        result = await get_members.handler({"group_id": 100})

        assert "members" in result
        assert len(result["members"]) == 2


class TestNapCatToolsVLM:
    """NapCatToolsPlugin: 配置 vision_model 后调 VLM 识图."""

    @pytest.fixture
    async def plugin_with_vlm(self):
        """配了 vision_model 的插件, agent.complete 返回 mock 描述."""
        gw = AsyncMock()
        gw.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {"user_id": 12345, "nickname": "TestUser"},
        })
        mock_agent = MagicMock()
        mock_agent.complete = AsyncMock(return_value=AgentResponse(
            text="一个卡通猫咪头像",
        ))
        bot = _make_bot(
            gateway=gw,
            agent=mock_agent,
            config_data={
                "plugins": {"napcat_tools": {"vision_model": "gpt-4o"}},
            },
        )
        p = NapCatToolsPlugin()
        await p.setup(bot)
        return p

    async def test_get_user_info_with_vlm_returns_description(self, plugin_with_vlm):
        tools = plugin_with_vlm.tools()
        get_user = next(t for t in tools if t.name == "get_user_info")
        result = await get_user.handler({"user_id": 12345})

        assert result["avatar_description"] == "一个卡通猫咪头像"
        assert "images_for_llm" not in result

    async def test_vlm_failure_returns_no_description(self):
        """VLM 调用失败时不中断, 只是没有 avatar_description."""
        gw = AsyncMock()
        gw.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {"user_id": 12345, "nickname": "TestUser"},
        })
        mock_agent = MagicMock()
        mock_agent.complete = AsyncMock(return_value=AgentResponse(
            error="model not available",
        ))
        bot = _make_bot(
            gateway=gw,
            agent=mock_agent,
            config_data={
                "plugins": {"napcat_tools": {"vision_model": "gpt-4o"}},
            },
        )
        p = NapCatToolsPlugin()
        await p.setup(bot)

        tools = p.tools()
        get_user = next(t for t in tools if t.name == "get_user_info")
        result = await get_user.handler({"user_id": 12345})

        # VLM 失败, 不应有 avatar_description, 但不应抛异常
        assert "avatar_description" not in result
        assert "12345" in result["avatar_url"]


class TestNapCatToolsPluginConfig:
    """插件配置: enabled_tools 过滤."""

    async def test_enabled_tools_filter(self):
        bot = _make_bot(config_data={
            "plugins": {"napcat_tools": {"enabled_tools": ["get_user_info", "get_message"]}},
        })
        p = NapCatToolsPlugin()
        await p.setup(bot)
        names = [t.name for t in p.tools()]

        assert "get_user_info" in names
        assert "get_message" in names
        assert "get_group_info" not in names

    async def test_no_filter_returns_all(self):
        bot = _make_bot()
        p = NapCatToolsPlugin()
        await p.setup(bot)
        names = {t.name for t in p.tools()}
        # 应包含所有已定义的查询工具
        assert "get_user_info" in names
        assert "get_group_info" in names
        assert "get_group_member_info" in names
        assert "get_group_member_list" in names
        assert "get_message" in names

# endregion


# region Agent attachment 提取

class TestExecuteToolAttachment:
    """_execute_tool: 从 handler 返回的 dict 中提取 attachments."""

    @pytest.fixture
    def agent(self):
        return LitellmAgent()

    async def test_dict_with_attachments_extracted(self, agent):
        # handler 返回含 attachments 的 dict → 分离成 (text, attachments)
        async def handler(params):
            return {
                "nickname": "Test",
                "attachments": [{"type": "image", "url": "https://example.com/img.jpg"}],
            }

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="test", description="test",
            parameters={}, handler=handler,
        ))

        text, attachments = await agent._execute_tool("test", {})
        parsed = json.loads(text)
        assert "nickname" in parsed
        # attachments 从 text 中移除
        assert "attachments" not in parsed
        assert len(attachments) == 1
        assert attachments[0].type == "image"
        assert attachments[0].url == "https://example.com/img.jpg"

    async def test_images_for_llm_ignored_as_plain_data(self, agent):
        # images_for_llm 不再有特殊处理, 当普通字段 json.dumps
        async def handler(params):
            return {
                "nickname": "Test",
                "images_for_llm": ["https://example.com/avatar.jpg"],
            }

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="vision", description="vision",
            parameters={}, handler=handler,
        ))

        result_content, attachments = await agent._execute_tool("vision", {})
        # result_content 是 str(json), images_for_llm 当普通字段序列化
        parsed = json.loads(result_content)
        assert parsed["images_for_llm"] == ["https://example.com/avatar.jpg"]
        assert attachments == []

    async def test_does_not_mutate_handler_return(self, agent):
        # _execute_tool 不应修改 handler 返回的原始 dict
        cached = {
            "data": "value",
            "attachments": [{"type": "image", "url": "https://example.com/img.jpg"}],
        }

        async def handler(params):
            return cached

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="cached", description="cached",
            parameters={}, handler=handler,
        ))

        await agent._execute_tool("cached", {})
        assert "attachments" in cached

    async def test_dict_without_attachments(self, agent):
        # 普通 dict → 无附件
        async def handler(params):
            return {"data": "plain"}

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="plain", description="plain",
            parameters={}, handler=handler,
        ))

        text, attachments = await agent._execute_tool("plain", {})
        assert json.loads(text) == {"data": "plain"}
        assert attachments == []

    async def test_str_result(self, agent):
        # handler 返回 str → 直接透传
        async def handler(params):
            return "just text"

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="str_tool", description="str",
            parameters={}, handler=handler,
        ))

        text, attachments = await agent._execute_tool("str_tool", {})
        assert text == "just text"
        assert attachments == []

    async def test_unknown_tool(self, agent):
        text, attachments = await agent._execute_tool("nonexistent", {})
        assert "error" in json.loads(text)
        assert attachments == []

    async def test_handler_exception(self, agent):
        async def handler(params):
            raise ValueError("boom")

        from acabot.agent.tool import ToolDef
        agent.register_tool(ToolDef(
            name="boom", description="boom",
            parameters={}, handler=handler,
        ))

        text, attachments = await agent._execute_tool("boom", {})
        assert "error" in json.loads(text)
        assert attachments == []

# endregion


# region Pipeline image segment

def _make_event(text="hello"):
    source = EventSource(
        platform="qq", message_type="private",
        user_id="123", group_id=None,
    )
    return StandardEvent(
        event_id="evt_1", event_type="message", platform="qq", timestamp=0,
        source=source, segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg_1", sender_nickname="T", sender_role=None,
    )


class TestBuildActionsImageSegment:
    """Pipeline._build_actions: image segment 的 file 字段格式."""

    @pytest.fixture
    def pipeline(self):
        return Pipeline(
            gateway=AsyncMock(),
            agent=AsyncMock(),
            session_mgr=InMemorySessionManager(),
        )

    def test_image_url_uses_file_field(self, pipeline):
        # URL 图片 → {"type": "image", "data": {"file": url}}
        resp = AgentResponse(
            text="描述文字",
            attachments=[Attachment(type="image", url="https://example.com/avatar.jpg")],
        )
        actions = pipeline._build_actions(_make_event(), resp)

        # 第一条是文本, 第二条是图片
        assert actions[0].action_type == ActionType.SEND_TEXT
        img_action = actions[1]
        assert img_action.action_type == ActionType.SEND_SEGMENTS
        seg = img_action.payload["segments"][0]
        assert seg["type"] == "image"
        assert seg["data"]["file"] == "https://example.com/avatar.jpg"
        assert "url" not in seg["data"]

    def test_image_base64_uses_file_with_prefix(self, pipeline):
        # base64 图片 → {"type": "image", "data": {"file": "base64://..."}}
        resp = AgentResponse(
            text="",
            attachments=[Attachment(type="image", data="iVBORw0KGgo=")],
        )
        actions = pipeline._build_actions(_make_event(), resp)

        # 无文本 → 只有图片 action
        assert len(actions) == 1
        seg = actions[0].payload["segments"][0]
        assert seg["data"]["file"] == "base64://iVBORw0KGgo="

    def test_image_no_url_no_data_skipped(self, pipeline):
        # 既无 url 也无 data → 跳过不生成 action
        resp = AgentResponse(
            text="text only",
            attachments=[Attachment(type="image")],
        )
        actions = pipeline._build_actions(_make_event(), resp)
        assert len(actions) == 1  # 只有文本

    def test_non_image_attachment(self, pipeline):
        # 非 image 类型 → 降级为文字占位
        resp = AgentResponse(
            text="",
            attachments=[Attachment(type="audio", url="https://example.com/a.mp3")],
        )
        actions = pipeline._build_actions(_make_event(), resp)
        seg = actions[0].payload["segments"][0]
        assert seg["type"] == "text"
        assert "audio" in seg["data"]["text"]

    def test_non_image_no_url_fallback(self, pipeline):
        # 非 image, url 为空 → 降级文案含 "(no url)"
        resp = AgentResponse(
            text="",
            attachments=[Attachment(type="audio")],
        )
        actions = pipeline._build_actions(_make_event(), resp)
        seg = actions[0].payload["segments"][0]
        assert "(no url)" in seg["data"]["text"]

# endregion
