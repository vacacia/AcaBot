"""runtime.backend.pi_adapter 提供真实的 pi RPC backend adapter.

Pi RPC JSONL 通信协议规则说明：
1. 采用标准输入输出 (stdin/stdout) 进行进程间通信, 通过 UTF-8 编码的单行 JSON 字符串 (JSON Lines, 简称 JSONL) 交互, 每条消息必须以 `\n` 结尾结尾.
2. 请求与响应匹配机制：
   - 适配器向 `pi` 的 stdin 发送指令时, Payload 中必须携带唯一的 `id` 字段（如 `"prompt:1"`）以及声明具体动作的 `type` 字段（如 `"get_state"`, `"prompt"`, `"fork"` 等）.
   - `pi` 处理后会在 stdout 返回诸如 `{"type": "response", "id": "...", "success": true/false, "data": {...}}` 的结果包, 适配器借此 `id` 进行非阻塞结果匹配.
3. 异步流式事件机制：
   - 对于诸如 `"prompt"` 这种伴随大模型生成的长耗时操作, 除了返回基础的 response 外, `pi` 还会不断向 stdout 吐出实时的状态事件.
   - 适配器需要通过阻塞循环持续吞咽事件流, 直到监听到终结事件（例如表示单次回答结束的 `"agent_end"` 事件包）, 才标志着模型输出收尾.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path


class PiBackendAdapter:
    """面向后台 session 的真实 pi RPC adapter.

    该适配层负责：
    - 启动 `pi --mode rpc`
    - 通过 JSONL stdin/stdout 与 pi 通信
    - 提供 change/query 所需的最小 prompt / fork 能力
    """

    def __init__(self, command: list[str], cwd: str | Path | None = None) -> None:
        """保存 adapter 启动参数.

        Args:
            command: 启动 pi 的命令行参数.
            cwd: pi 进程工作目录.
        """

        self.command = list(command)
        self.cwd = None if cwd is None else Path(cwd)
        self.started = False
        self._process: asyncio.subprocess.Process | None = None
        self._request_counter = 0
        self._stdout_lock = asyncio.Lock()

    def is_command_available(self) -> bool:
        """返回当前 pi 命令是否在本机可执行.

        这里是 Task 2 review 后补上的硬检查：
        - 不能只因为 config 里写了 `enabled=true` 和 `pi_command` 非空, 就把 backend 报成 configured。
        - 至少要先确认 command[0] 在当前环境里可解析/可执行, 否则 control plane 和路由层会被误导。
        """

        if not self.command:
            return False
        executable = self.command[0]
        if Path(executable).is_absolute():
            return Path(executable).exists()
        return shutil.which(executable) is not None

    async def ensure_started(self) -> dict[str, object]:
        """确保 pi RPC 进程已启动并返回当前 state."""

        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=None if self.cwd is None else str(self.cwd),
            )
            self.started = True
        return await self._request_response({"type": "get_state"}, command="get_state")

    async def switch_session(self, session_path: str) -> dict[str, object]:
        """切换到指定 session 文件并返回 switch 响应.

        踩坑记录：
        - `switch_session()` 本身是有效的，重启后的新进程也确实能切回旧 session。
        - 但如果对“当前已经打开的同一个 session 文件”再调用一次 `switch_session()`，
          `pi` 可能返回一个新的 `sessionId`，导致我们误以为 canonical session 变了。
        - 所以是否调用 `switch_session()` 的判断必须放在 session service 层，基于
          `current sessionFile != binding.session_file` 再执行，而不是在 adapter 层无脑切。
        """

        await self.ensure_started()
        return await self._request_response(
            {"type": "switch_session", "sessionPath": session_path},
            command="switch_session",
        )

    async def prompt(self, prompt: str) -> dict[str, object]:
        """在当前 canonical pi session 中发送一条 prompt 并等待完成.

        踩坑记录：
        - 这里不能返回 prompt 之前那次 `get_state()` 的 session 元数据。
        - review 已经指出: 如果 `pi` 在 prompt 路径里改变了 `sessionId/sessionFile`，
          binding 会被写回旧值, canonical binding 仍然可能漂移。
        - 所以这里必须返回 prompt 结束后的真实 state。
        """

        await self.ensure_started()
        response, text, agent_end = await self._run_prompt(prompt)
        state_after = await self._request_response({"type": "get_state"}, command="get_state")
        return {
            "transport": "rpc",
            "command": list(self.command),
            "prompt": prompt,
            "response": response,
            "agent_end": agent_end,
            "text": text,
            "session_id": state_after["data"]["sessionId"],
            "session_file": state_after["data"].get("sessionFile", ""),
        }

    async def fork_from_stable_checkpoint(self, prompt: str) -> dict[str, object]:
        """从最近可 fork 的用户消息创建 query fork 后执行 prompt.

        踩坑记录：
        - 真实 fork 机制是工作的，但测试提示词如果写得太松，模型有时会跑偏，导致看起来像
          fork 失败，实际是提示词不稳。
        - 所以测试 query/fork 时要尽量用非常收束的文案，避免把“模型回答波动”误判成
          “fork 机制失效”。
        """

        state = await self.ensure_started()
        fork_messages = await self._request_response(
            {"type": "get_fork_messages"},
            command="get_fork_messages",
        )
        messages = list(fork_messages.get("data", {}).get("messages", []))
        if not messages:
            response, text, agent_end = await self._run_prompt(prompt)
            state_after = await self._request_response({"type": "get_state"}, command="get_state")
            return {
                "transport": "rpc",
                "command": list(self.command),
                "prompt": prompt,
                "response": response,
                "agent_end": agent_end,
                "text": text,
                "session_id": state_after["data"]["sessionId"],
                "session_file": state_after["data"].get("sessionFile", ""),
                "forked": False,
            }

        entry_id = str(messages[-1]["entryId"])
        await self._request_response(
            {"type": "fork", "entryId": entry_id},
            command="fork",
        )
        response, text, agent_end = await self._run_prompt(prompt)
        fork_state = await self._request_response({"type": "get_state"}, command="get_state")
        return {
            "transport": "rpc",
            "command": list(self.command),
            "prompt": prompt,
            "response": response,
            "agent_end": agent_end,
            "text": text,
            "session_id": fork_state["data"]["sessionId"],
            "session_file": fork_state["data"].get("sessionFile", ""),
            "forked": True,
        }

    async def dispose(self) -> None:
        """释放当前 pi 进程."""

        process = self._process
        self._process = None
        self.started = False
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def _run_prompt(self, prompt: str) -> tuple[dict[str, object], str, dict[str, object]]:
        """发送 prompt 并等待 agent_end, 返回 response/text/agent_end."""

        response = await self._send_command({"type": "prompt", "message": prompt}, command="prompt")
        agent_end = await self._read_until_event("agent_end")
        text = self._extract_last_assistant_text(agent_end)
        return response, text, agent_end

    async def _request_response(self, payload: dict[str, object], *, command: str) -> dict[str, object]:
        """发送一个非流式命令并等待对应 response."""

        return await self._send_command(payload, command=command)

    async def _send_command(self, payload: dict[str, object], *, command: str) -> dict[str, object]:
        """发送命令并读取对应 response."""

        process = self._process
        if process is None or process.stdin is None:
            await self.ensure_started()
            process = self._process
        assert process is not None
        assert process.stdin is not None
        async with self._stdout_lock:
            request_id = self._next_request_id(command)
            body = dict(payload)
            body["id"] = request_id
            process.stdin.write((json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()
            while True:
                event = await self._read_jsonl_locked()
                if event.get("type") == "response" and event.get("id") == request_id:
                    if not event.get("success", False):
                        raise RuntimeError(str(event.get("error", "pi rpc command failed")))
                    return event

    async def _read_until_event(self, event_type: str) -> dict[str, object]:
        """读取 stdout 直到匹配目标事件类型."""

        assert self._process is not None
        async with self._stdout_lock:
            while True:
                event = await self._read_jsonl_locked()
                if event.get("type") == event_type:
                    return event

    async def _read_jsonl_locked(self) -> dict[str, object]:
        """读取一条 JSONL 事件.

        调用方必须已持有 `_stdout_lock`.
        """

        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("pi process is not running")
        line = await process.stdout.readline()
        if not line:
            stderr = ""
            if process.stderr is not None:
                stderr_bytes = await process.stderr.read()
                stderr = stderr_bytes.decode("utf-8", errors="replace")
            raise RuntimeError(f"pi rpc stream closed unexpectedly: {stderr}")
        return json.loads(line.decode("utf-8").rstrip("\r\n"))

    def _next_request_id(self, prefix: str) -> str:
        """生成单进程内唯一 request id."""

        self._request_counter += 1
        return f"{prefix}:{self._request_counter}"

    def _extract_last_assistant_text(self, agent_end: dict[str, object]) -> str:
        """从 agent_end 事件中提取最后一条 assistant text."""

        messages = list(agent_end.get("messages", []))
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            parts = list(message.get("content", []))
            text_parts = [
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            text = "".join(text_parts).strip()
            if text:
                return text
        return ""
