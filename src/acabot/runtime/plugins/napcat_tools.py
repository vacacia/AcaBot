"""runtime.plugins.napcat_tools 提供 NapCat 查询工具插件.

组件关系:

    RuntimePluginManager
            |
            v
     NapCatToolsPlugin
            |
            v
      gateway.call_api()

查询类 QQ 能力:
- get_user_info
- get_group_info
- get_group_member_info
- get_group_member_list
- get_message
"""

from __future__ import annotations

import logging
from typing import Any

from acabot.agent import ToolDef

from ..plugin_manager import RuntimePlugin, RuntimePluginContext

logger = logging.getLogger("acabot.runtime.plugin.napcat_tools")

_AVATAR_URL_TEMPLATE = "https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"


# region plugin
class NapCatToolsPlugin(RuntimePlugin):
    """NapCat 查询工具插件.

    Attributes:
        name (str): 插件名.
        _gateway (Any): 当前 gateway 实例.
        _enabled_tools (set[str]): 当前启用工具名集合.
    """

    name = "napcat_tools"

    def __init__(self) -> None:
        """初始化插件状态."""

        self._gateway: Any = None
        self._enabled_tools: set[str] = set()

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """保存 gateway 并读取插件配置.

        Args:
            runtime: runtime plugin 上下文.
        """

        self._gateway = runtime.gateway
        config = runtime.get_plugin_config(self.name)
        self._enabled_tools = {
            str(tool_name)
            for tool_name in list(config.get("enabled_tools", []) or [])
            if str(tool_name)
        }

    def tools(self) -> list[ToolDef]:
        """返回要注册的 NapCat 查询工具.

        Returns:
            过滤后的 ToolDef 列表.
        """

        all_tools = [
            self._get_user_info_tool(),
            self._get_group_info_tool(),
            self._get_group_member_info_tool(),
            self._get_group_member_list_tool(),
            self._get_message_tool(),
        ]
        if not self._enabled_tools:
            return all_tools
        return [tool for tool in all_tools if tool.name in self._enabled_tools]

    # region tools
    def _get_user_info_tool(self) -> ToolDef:
        """构造 get_user_info 工具定义."""

        return ToolDef(
            name="get_user_info",
            description=(
                "查询 QQ 用户信息. "
                "返回 JSON, 包含 nickname, user_id, avatar_url 等字段."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "QQ 号",
                    },
                },
                "required": ["user_id"],
            },
            handler=self._handle_get_user_info,
        )

    def _get_group_info_tool(self) -> ToolDef:
        """构造 get_group_info 工具定义."""

        return ToolDef(
            name="get_group_info",
            description="查询 QQ 群信息, 如群名和成员数.",
            parameters={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "群号",
                    },
                },
                "required": ["group_id"],
            },
            handler=self._handle_get_group_info,
        )

    def _get_group_member_info_tool(self) -> ToolDef:
        """构造 get_group_member_info 工具定义."""

        return ToolDef(
            name="get_group_member_info",
            description="查询某个群成员的详细信息, 如群名片和角色.",
            parameters={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "群号",
                    },
                    "user_id": {
                        "type": "integer",
                        "description": "QQ 号",
                    },
                },
                "required": ["group_id", "user_id"],
            },
            handler=self._handle_get_group_member_info,
        )

    def _get_group_member_list_tool(self) -> ToolDef:
        """构造 get_group_member_list 工具定义."""

        return ToolDef(
            name="get_group_member_list",
            description="获取群成员列表, 返回 members 数组.",
            parameters={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "群号",
                    },
                },
                "required": ["group_id"],
            },
            handler=self._handle_get_group_member_list,
        )

    def _get_message_tool(self) -> ToolDef:
        """构造 get_message 工具定义."""

        return ToolDef(
            name="get_message",
            description="根据消息 ID 获取消息详情.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "integer",
                        "description": "消息 ID",
                    },
                },
                "required": ["message_id"],
            },
            handler=self._handle_get_message,
        )

    # endregion

    # region handlers
    async def _handle_get_user_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 get_user_info."""

        user_id = int(params["user_id"])
        data = await self._call_api("get_stranger_info", {"user_id": user_id})
        data["avatar_url"] = self._resolve_avatar_url(data, user_id)
        return data

    async def _handle_get_group_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 get_group_info."""

        return await self._call_api("get_group_info", {"group_id": int(params["group_id"])})

    async def _handle_get_group_member_info(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """处理 get_group_member_info."""

        group_id = int(params["group_id"])
        user_id = int(params["user_id"])
        data = await self._call_api(
            "get_group_member_info",
            {"group_id": group_id, "user_id": user_id},
        )
        data["avatar_url"] = self._resolve_avatar_url(data, user_id)
        return data

    async def _handle_get_group_member_list(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """处理 get_group_member_list."""

        data = await self._call_api("get_group_member_list", {"group_id": int(params["group_id"])})
        return {"members": data}

    async def _handle_get_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 get_message."""

        return await self._call_api("get_msg", {"message_id": int(params["message_id"])})

    # endregion

    # region helpers
    async def _call_api(self, action: str, params: dict[str, Any]) -> Any:
        """统一的 API 调用和错误检查.

        Args:
            action: NapCat OneBot API 名称.
            params: API 参数.

        Returns:
            成功时的 `data` 字段.

        Raises:
            RuntimeError: 当前 gateway 不支持 `call_api`, 或平台返回失败.
        """

        call_api = getattr(self._gateway, "call_api", None)
        if not callable(call_api):
            raise RuntimeError("gateway.call_api unavailable")
        resp = await call_api(action, params)
        if resp.get("status") == "ok":
            return resp.get("data", {})
        message = str(resp.get("msg") or resp.get("wording") or "API call failed")
        logger.warning("NapCat API %s failed: %s (params=%s)", action, message, params)
        raise RuntimeError(f"{action}: {message}")

    @staticmethod
    def _resolve_avatar_url(data: dict[str, Any], user_id: int) -> str:
        """从 API 返回中提取头像 URL.

        Args:
            data: API 返回数据.
            user_id: 当前用户 QQ 号.

        Returns:
            命中的头像 URL, 或按 qlogo 模板拼接的地址.
        """

        for key in ("avatar", "avatar_url", "face", "face_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        return _AVATAR_URL_TEMPLATE.format(user_id=user_id)

    # endregion


# endregion
