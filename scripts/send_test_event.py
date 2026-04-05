#!/usr/bin/env python3
"""给 AcaBot 注入 OneBot v11 测试事件的小工具."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import websockets


DEFAULT_WS_URL = "ws://127.0.0.1:8080"
DEFAULT_TOKEN = "80iV<RBrHtQdmp0r"
DEFAULT_SELF_ID = "3482263824"
DEFAULT_USER_ID = "10001"
DEFAULT_GROUP_ID = "1039173249"


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器."""

    parser = argparse.ArgumentParser(description="向 AcaBot 网关注入一条 OneBot v11 测试事件")
    parser.add_argument("--url", default=DEFAULT_WS_URL, help=f"目标 WS 地址, 默认 {DEFAULT_WS_URL}")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="NapCat 反向 WS token")
    parser.add_argument("--self-id", default=DEFAULT_SELF_ID, help="bot 自己的 QQ 号, 会写进 X-Self-ID")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="伪造发送者 QQ 号")
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID, help="群号, 私聊模式下忽略")
    parser.add_argument("--nickname", default="TestUser", help="伪造发送者昵称")
    parser.add_argument("--text", default="测试消息", help="文本内容")
    parser.add_argument(
        "--message-type",
        choices=["private", "group"],
        default="private",
        help="OneBot message_type",
    )
    parser.add_argument("--sub-type", default="friend", help="OneBot sub_type")
    parser.add_argument("--message-id", default="", help="指定平台 message_id, 默认自动生成")
    parser.add_argument("--reply-id", default="", help="附带 reply segment, 指向上游消息 id")
    parser.add_argument("--reply-user-id", default="", help="reply segment 中的 user_id (被回复消息的发送者 QQ, 默认使用 --self-id)")
    parser.add_argument("--mention-self", action="store_true", help="群聊里附带 @bot")
    parser.add_argument("--wait-seconds", type=float, default=8.0, help="发送后等待 bot 回包的秒数")
    parser.add_argument(
        "--raw-file",
        default="",
        help="直接从 JSON 文件读取完整 OneBot payload. 提供后, 其余事件字段参数会被忽略",
    )
    parser.add_argument(
        "--notice-type",
        default="",
        choices=["poke", "recall", "member_leave", "member_join", "admin_change", "file_upload", "mute_change", "honor_change", "title_change", "lucky_king"],
        help="发送 notice event 而非 message event",
    )
    parser.add_argument("--notice-sub-type", default="", help="notice 子类型, 如 poke 时的 action (poke, kiss, etc.)")
    return parser


def _build_message_segments(args: argparse.Namespace) -> list[dict[str, Any]]:
    """根据 CLI 参数拼 OneBot message segment."""

    segments: list[dict[str, Any]] = []
    if args.reply_id:
        reply_data: dict[str, Any] = {"id": str(args.reply_id)}
        reply_user_id = args.reply_user_id or args.self_id
        reply_data["user_id"] = int(reply_user_id)
        segments.append({"type": "reply", "data": reply_data})
    if args.message_type == "group" and args.mention_self:
        segments.append({"type": "at", "data": {"qq": str(args.self_id)}})
    if args.text:
        segments.append({"type": "text", "data": {"text": str(args.text)}})
    return segments


def build_message_event(args: argparse.Namespace) -> dict[str, Any]:
    """构造一条 OneBot v11 message event."""

    message_id = str(args.message_id or int(time.time() * 1000))
    payload: dict[str, Any] = {
        "time": int(time.time()),
        "self_id": int(args.self_id),
        "post_type": "message",
        "message_type": args.message_type,
        "sub_type": args.sub_type,
        "message_id": int(message_id),
        "user_id": int(args.user_id),
        "message": _build_message_segments(args),
        "raw_message": args.text,
        "font": 14,
        "sender": {
            "user_id": int(args.user_id),
            "nickname": args.nickname,
            "sex": "unknown",
            "age": 0,
        },
    }
    if args.message_type == "group":
        payload["group_id"] = int(args.group_id)
        payload["sender"]["card"] = ""
        payload["sender"]["role"] = "member"
    return payload


def build_notice_event(args: argparse.Namespace) -> dict[str, Any]:
    """构造一条 OneBot v11 notice event."""

    # CLI 类型 → OneBot notice_type 映射
    notice_type_map = {
        "recall": "group_recall",
        "member_leave": "group_decrease",
        "member_join": "group_increase",
        "admin_change": "group_admin",
        "file_upload": "group_upload",
        "mute_change": "group_ban",
    }
    cli_notice_type = args.notice_type
    notice_type = notice_type_map.get(cli_notice_type, cli_notice_type)
    sub_type = args.notice_sub_type or ""

    # notify 类型的 notice 使用 notice_type="notify", sub_type 才是真正的子类型
    notify_sub_type_map = {
        "poke": "poke",
        "lucky_king": "lucky_king",
        "honor_change": "honor",
        "title_change": "title",
    }
    if cli_notice_type in notify_sub_type_map:
        payload: dict[str, Any] = {
            "time": int(time.time()),
            "self_id": int(args.self_id),
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": notify_sub_type_map[cli_notice_type],
        }
    else:
        payload = {
            "time": int(time.time()),
            "self_id": int(args.self_id),
            "post_type": "notice",
            "notice_type": notice_type,
        }

    if cli_notice_type == "poke":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["target_id"] = int(args.self_id)
        payload["sender_id"] = int(args.user_id)
        payload["action"] = sub_type or "poke"
        payload["suffix"] = ""

    elif cli_notice_type == "recall":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["message_id"] = int(args.message_id) if args.message_id else int(time.time() * 1000)
        payload["operator_id"] = int(args.user_id)

    elif cli_notice_type == "member_leave":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["member"] = {"user_id": int(args.user_id), "nickname": args.nickname}
        payload["dismiss"] = False

    elif cli_notice_type == "member_join":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["member"] = {"user_id": int(args.user_id), "nickname": args.nickname}
        payload["invitor_id"] = int(args.user_id)

    elif cli_notice_type == "admin_change":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["set"] = True  # True = 设置为管理员, False = 取消管理员

    elif cli_notice_type == "file_upload":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["file"] = {"id": "file_test", "name": "test.txt", "size": 1024, "busid": 0}

    elif cli_notice_type == "mute_change":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["operator_id"] = int(args.self_id)
        payload["mute_duration"] = 300  # 5分钟

    elif cli_notice_type == "honor_change":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["honor_type"] = "talkative"

    elif cli_notice_type == "title_change":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["title"] = "测试称号"

    elif cli_notice_type == "lucky_king":
        payload["group_id"] = int(args.group_id)
        payload["user_id"] = int(args.user_id)
        payload["message_id"] = int(args.message_id) if args.message_id else int(time.time() * 1000)

    return payload


async def send_event(args: argparse.Namespace) -> int:
    """连接 gateway, 注入事件, 然后等待 bot 回包."""

    headers = {
        "Authorization": f"Bearer {args.token}",
        "X-Self-ID": str(args.self_id),
        "X-Client-Role": "Universal",
        "User-Agent": "acabot-test-event/1.0",
    }
    if args.raw_file:
        with open(args.raw_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    elif args.notice_type:
        payload = build_notice_event(args)
    else:
        payload = build_message_event(args)

    print("=== outbound test event ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    async with websockets.connect(args.url, additional_headers=headers) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print(f"\n已发送到 {args.url}, 开始等待 {args.wait_seconds:.1f}s 回包...\n")

        deadline = time.monotonic() + max(args.wait_seconds, 0.0)
        received_anything = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            received_anything = True
            data = json.loads(raw)
            print("=== inbound from acabot ===")
            print(json.dumps(data, ensure_ascii=False, indent=2))

            echo = data.get("echo")
            if echo:
                ack = {"status": "ok", "retcode": 0, "data": {"message_id": f"fake:{echo}"}, "echo": echo}
                await ws.send(json.dumps(ack, ensure_ascii=False))
                print("=== ack sent ===")
                print(json.dumps(ack, ensure_ascii=False, indent=2))

        if not received_anything:
            print("等待窗口里没有收到任何 bot 回包")
        return 0


def main() -> int:
    """CLI 入口."""

    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(send_event(args))


if __name__ == "__main__":
    raise SystemExit(main())
