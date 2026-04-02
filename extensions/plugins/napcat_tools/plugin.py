"""NapCatToolsPlugin — 把 NapCat OneBot API 封装为 LLM 可调用的工具.

v0.4 只包含查询类工具(get_user_info / get_group_info 等),
操作类(ban/kick/recall)需要权限控制, 留到后续版本.

插件配置(config.yaml):
    plugins:
      napcat_tools:
        enabled_tools:         # 留空则注册全部
          - get_user_info
          - get_group_info
        vision_model: ""       # 头像识图模型, 留空则不识图只返回 URL
"""

from __future__ import annotations

import logging
from typing import Any

from acabot.agent import ToolDef
from acabot.plugin.base import Plugin
from acabot.plugin.context import BotContext
from acabot.types import HookPoint

logger = logging.getLogger("acabot.plugin.napcat_tools")

# QQ 头像 URL 模板, s=640 取最大尺寸
_AVATAR_URL_TEMPLATE = "https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"


class NapCatToolsPlugin(Plugin):
    """NapCat 查询工具集.

    纯 tool 插件, 无 hook. 通过 gateway.call_api 调用 OneBot API,
    把结果转换成 LLM 友好的 JSON 返回.

    Attributes:
        name: 插件标识, 用于去重和配置读取.
    """

    name = "napcat_tools"

    async def setup(self, bot: BotContext) -> None:
        """保存 bot 引用, 读取插件配置."""
        self._bot = bot
        self._gateway = bot.gateway
        self._config = bot.get_config(self.name)
        self._vision_model: str = self._config.get("vision_model", "")

    def hooks(self) -> list[tuple[HookPoint, Any]]:
        return []

    def tools(self) -> list[ToolDef]:
        """根据配置过滤, 返回要注册的工具列表."""
        all_tools = [
            self._get_user_info_tool(),
            self._get_group_info_tool(),
            self._get_group_member_info_tool(),
            self._get_group_member_list_tool(),
            self._get_message_tool(),
        ]
        enabled = self._config.get("enabled_tools")
        if enabled:
            return [t for t in all_tools if t.name in enabled]
        return all_tools

    # region 工具定义

    def _get_user_info_tool(self) -> ToolDef:
        return ToolDef(
            name="get_user_info",
            description=(
                "查询 QQ 用户信息(昵称, 头像等). "
                "返回 JSON 含 nickname, user_id, avatar_url 字段."
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
        return ToolDef(
            name="get_group_info",
            description="查询 QQ 群信息(群名, 成员数等).",
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
        return ToolDef(
            name="get_group_member_info",
            description="查询某个群成员的详细信息(昵称, 群名片, 角色等).",
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
        return ToolDef(
            name="get_group_member_list",
            description="获取群成员列表(user_id, nickname, card, role).",
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
        return ToolDef(
            name="get_message",
            description="根据消息 ID 获取消息详情(内容, 发送者等).",
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

    # region 工具 handler

    @staticmethod
    def _resolve_avatar_url(data: dict[str, Any], user_id: int) -> str:
        """从 API 返回中提取头像 URL, 找不到则拼接 qlogo.

        NapCat 不同版本/API 返回头像的字段名不统一,
        参考 astrbot_plugin_response_enhancer 的多字段探测.
        """
        for key in ("avatar", "avatar_url", "face", "face_url"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                return val
        return _AVATAR_URL_TEMPLATE.format(user_id=user_id)

    async def _describe_avatar(self, avatar_url: str) -> str | None:
        """调 VLM 描述头像图片, 无 vision_model 配置则返回 None.

        通过 bot.llm_complete() 调用, 不走 tool loop.
        失败时记录日志并返回 None, 不中断工具流程.
        """
        if not self._vision_model:
            return None
        try:
            resp = await self._bot.llm_complete(
                system_prompt="简洁描述这张头像图片的内容, 一两句话即可.",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "描述这张头像:"},
                        {"type": "image_url", "image_url": {"url": avatar_url}},
                    ],
                }],
                model=self._vision_model,
            )
            if resp.error:
                logger.warning("VLM 识图失败: %s", resp.error)
                return None
            return resp.text.strip() or None
        except Exception as e:
            logger.warning("VLM 识图异常: %s", e)
            return None

    async def _call_api(self, action: str, params: dict[str, Any]) -> Any:
        """统一的 API 调用 + 错误检查.

        Args:
            action: OneBot API 名, 如 "get_stranger_info".
            params: API 参数.

        Returns:
            成功时返回 response["data"](dict 或 list, 取决于具体 API).

        Raises:
            RuntimeError: API 调用失败(retcode != 0).
        """
        resp = await self._gateway.call_api(action, params)
        if resp.get("status") == "ok":
            return resp.get("data", {})
        msg = resp.get("msg") or resp.get("wording") or "API call failed"
        logger.warning("NapCat API %s failed: %s (params=%s)", action, msg, params)
        raise RuntimeError(f"{action}: {msg}")

    async def _handle_get_user_info(self, params: dict[str, Any]) -> dict[str, Any]:
        user_id = params["user_id"]
        data = await self._call_api("get_stranger_info", {"user_id": user_id})
        avatar_url = self._resolve_avatar_url(data, user_id)
        data["avatar_url"] = avatar_url
        description = await self._describe_avatar(avatar_url)
        if description:
            data["avatar_description"] = description
        return data

    async def _handle_get_group_info(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._call_api("get_group_info", {"group_id": params["group_id"]})

    async def _handle_get_group_member_info(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._call_api(
            "get_group_member_info",
            {"group_id": params["group_id"], "user_id": params["user_id"]},
        )
        user_id = params["user_id"]
        avatar_url = self._resolve_avatar_url(data, user_id)
        data["avatar_url"] = avatar_url
        description = await self._describe_avatar(avatar_url)
        if description:
            data["avatar_description"] = description
        return data

    async def _handle_get_group_member_list(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        data = await self._call_api(
            "get_group_member_list", {"group_id": params["group_id"]},
        )
        # data 是 list, 包一层以保持 JSON 格式一致
        return {"members": data}

    async def _handle_get_message(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._call_api("get_msg", {"message_id": params["message_id"]})

    # endregion
