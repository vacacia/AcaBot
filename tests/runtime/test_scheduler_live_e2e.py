"""scheduler 真实 LLM 端到端测试.

这组测试不使用 fake agent, 而是连接已经运行的 AcaBot runtime,
通过真实模型完成:
- 自然语言请求创建定时提醒
- LLM 自主选择 scheduler 工具
- scheduler 触发 synthetic event
- 原会话再次唤醒 LLM 并回复提醒

默认需要手动开启:
- ACABOT_LIVE_E2E=1
- 本地存在 docker 容器 `acabot`
- 本地 HTTP API 可通过 `http://127.0.0.1:8765` 访问
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pytest

LIVE_ENABLED = os.getenv("ACABOT_LIVE_E2E", "").lower() in {"1", "true", "yes", "on"}
LIVE_BASE_URL = os.getenv("ACABOT_LIVE_BASE_URL", "http://127.0.0.1:8765")
LIVE_RUNTIME_CONTAINER = os.getenv("ACABOT_LIVE_RUNTIME_CONTAINER", "acabot")
LIVE_CONVERSATION_ID = "qq:group:1097619430"
LIVE_THREAD_ID = LIVE_CONVERSATION_ID
LIVE_SENDER_USER_ID = "1733064202"
LIVE_TOKEN_PREFIX = "sched-live-"
LIVE_REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_RUNTIME_DB_PATH = LIVE_REPO_ROOT / "runtime_data" / "db" / "acabot.db"

pytestmark = pytest.mark.skipif(not LIVE_ENABLED, reason="set ACABOT_LIVE_E2E=1 to run live scheduler e2e")


def _request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{LIVE_BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _docker_exec_request_json_with_status(
    path: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    command = [
        "docker",
        "exec",
        "-i",
        LIVE_RUNTIME_CONTAINER,
        "python",
        "-c",
        (
            "import json, sys;"
            "from urllib.error import HTTPError;"
            "from urllib.request import Request, urlopen;"
            "envelope=json.load(sys.stdin);"
            "data=None; headers={};"
            "payload=envelope.get('payload');"
            "method=envelope.get('method','GET');"
            "path=envelope['path'];"
            "\nif payload is not None:\n"
            "    data=json.dumps(payload).encode('utf-8');\n"
            "    headers['Content-Type']='application/json';\n"
            "req=Request('http://127.0.0.1:8765'+path, data=data, headers=headers, method=method);"
            "\ntry:\n"
            "    resp=urlopen(req, timeout=180);\n"
            "    print(json.dumps({'status': resp.status, 'body': json.loads(resp.read().decode('utf-8'))}))\n"
            "except HTTPError as exc:\n"
            "    raw=exc.read().decode('utf-8');\n"
            "    try:\n"
            "        body=json.loads(raw)\n"
            "    except Exception:\n"
            "        body={'raw': raw}\n"
            "    print(json.dumps({'status': exc.code, 'body': body}))\n"
        ),
    ]
    completed = subprocess.run(
        command,
        input=json.dumps({"path": path, "method": method, "payload": payload}),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(completed.stdout)
    status = int(response.get("status", 0) or 0)
    body = response.get("body", {})
    return status, body


async def _wait_for(predicate, *, timeout: float, interval: float = 1.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _get_session_agent() -> dict[str, Any]:
    response = _request_json(f"/api/sessions/{LIVE_CONVERSATION_ID}/agent")
    assert response["ok"] is True
    return dict(response["data"])


def _session_agent_update_payload(view: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt_ref": str(view.get("prompt_ref", "") or ""),
        "visible_tools": [str(item) for item in list(view.get("visible_tools", []) or [])],
        "visible_skills": [str(item) for item in list(view.get("visible_skills", []) or [])],
        "visible_subagents": [str(item) for item in list(view.get("visible_subagents", []) or [])],
    }
    model_target = str(view.get("model_target", "") or "").strip()
    if model_target:
        payload["model_target"] = model_target
    computer_policy = view.get("computer_policy")
    if isinstance(computer_policy, dict):
        payload["computer_policy"] = dict(computer_policy)
    return payload


def _put_session_agent(view: dict[str, Any]) -> dict[str, Any]:
    response = _request_json(
        f"/api/sessions/{LIVE_CONVERSATION_ID}/agent",
        method="PUT",
        payload=_session_agent_update_payload(view),
    )
    assert response["ok"] is True
    return dict(response["data"])


def _list_thread_events(limit: int = 50) -> list[dict[str, Any]]:
    response = _request_json(f"/api/runtime/threads/{LIVE_THREAD_ID}/events?limit={limit}")
    assert response["ok"] is True
    return list(response["data"])


def _list_thread_messages(limit: int = 50) -> list[dict[str, Any]]:
    response = _request_json(f"/api/runtime/threads/{LIVE_THREAD_ID}/messages?limit={limit}")
    assert response["ok"] is True
    return list(response["data"])


def _get_run(run_id: str) -> dict[str, Any]:
    response = _request_json(f"/api/runtime/runs/{run_id}")
    assert response["ok"] is True
    return dict(response["data"])


def _list_live_test_scheduled_tasks(*, token: str | None = None) -> list[dict[str, Any]]:
    assert LIVE_RUNTIME_DB_PATH.exists(), f"runtime db not found: {LIVE_RUNTIME_DB_PATH}"
    with sqlite3.connect(LIVE_RUNTIME_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        marker = token or LIVE_TOKEN_PREFIX
        rows = conn.execute(
            "SELECT task_id, owner, schedule_type, schedule_spec, next_fire_at, enabled, metadata_json "
            "FROM scheduled_tasks WHERE owner = ? AND metadata_json LIKE ? ORDER BY created_at ASC",
            (LIVE_CONVERSATION_ID, f"%{marker}%"),
        ).fetchall()
    tasks: list[dict[str, Any]] = []
    for row in rows:
        tasks.append(
            {
                "task_id": str(row["task_id"]),
                "owner": str(row["owner"]),
                "schedule_type": str(row["schedule_type"]),
                "schedule_spec": json.loads(str(row["schedule_spec"] or "{}")),
                "next_fire_at": row["next_fire_at"],
                "enabled": bool(row["enabled"]),
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
            }
        )
    return tasks


def _delete_live_test_scheduled_tasks() -> int:
    command = [
        "docker",
        "exec",
        "-i",
        LIVE_RUNTIME_CONTAINER,
        "python",
        "-c",
        (
            "import json, sqlite3, sys;"
            "payload=json.load(sys.stdin);"
            "conn=sqlite3.connect('/app/runtime_data/db/acabot.db');"
            "row=conn.execute("
            "\"SELECT COUNT(*) FROM scheduled_tasks WHERE owner = ? AND metadata_json LIKE ?\""
            ", (payload['owner'], payload['pattern'])).fetchone();"
            "count=int(row[0] if row else 0);"
            "conn.execute("
            "\"DELETE FROM scheduled_tasks WHERE owner = ? AND metadata_json LIKE ?\""
            ", (payload['owner'], payload['pattern']));"
            "conn.commit();"
            "print(json.dumps({'count': count}))"
        ),
    ]
    completed = subprocess.run(
        command,
        input=json.dumps({"owner": LIVE_CONVERSATION_ID, "pattern": f"%{LIVE_TOKEN_PREFIX}%"}),
        text=True,
        capture_output=True,
        check=True,
    )
    return int(json.loads(completed.stdout).get("count", 0) or 0)


def _restart_runtime_container() -> None:
    subprocess.run(
        ["docker", "restart", LIVE_RUNTIME_CONTAINER],
        check=True,
        capture_output=True,
        text=True,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            response = _request_json("/api/status")
        except Exception:
            time.sleep(2.0)
            continue
        if response.get("ok") is True:
            return
        time.sleep(2.0)
    raise AssertionError("runtime did not become ready after container restart")


async def test_scheduler_live_llm_e2e_uses_natural_language_and_fires_back_into_group() -> None:
    original_agent = _get_session_agent()
    updated_agent = dict(original_agent)
    visible_tools = [str(item) for item in list(updated_agent.get("visible_tools", []) or [])]
    if "scheduler" not in visible_tools:
        visible_tools.append("scheduler")
    updated_agent["visible_tools"] = visible_tools
    updated_agent["computer_policy"] = {
        **dict(updated_agent.get("computer_policy") or {}),
        "allow_exec": False,
        "allow_sessions": False,
    }

    cleanup_deleted = _delete_live_test_scheduled_tasks()
    _restart_runtime_container()

    token = f"{LIVE_TOKEN_PREFIX}{int(time.time())}"
    reminder_phrase = f"口令 {token}"
    evidence: dict[str, Any] = {
        "token": token,
        "conversation_id": LIVE_CONVERSATION_ID,
        "sender_user_id": LIVE_SENDER_USER_ID,
        "base_url": LIVE_BASE_URL,
        "container": LIVE_RUNTIME_CONTAINER,
        "cleanup_deleted_task_count": cleanup_deleted,
    }

    try:
        _put_session_agent(updated_agent)

        injection_status, injection = _docker_exec_request_json_with_status(
            "/api/runtime/events",
            method="POST",
            payload={
                "conversation_id": LIVE_CONVERSATION_ID,
                "sender_user_id": LIVE_SENDER_USER_ID,
                "sender_nickname": "live-scheduler-e2e",
                "targets_self": True,
                "mentions_self": True,
                "text": (
                    f"帮我设一个一次性的稍后提醒。大约60秒后，只提醒这一次，"
                    f"请你直接提醒我：“提醒你，{reminder_phrase}”。"
                    f"这句话里的口令必须原样保留，不要改写。"
                    f"请你真的把这次提醒安排好，不要只是口头答应。"
                    f"现在先简短确认你记下了，不要立刻提醒。"
                ),
            },
        )
        evidence["injection_status"] = injection_status
        evidence["injection"] = injection

        initial_event = await _wait_for(
            lambda: next(
                (
                    item
                    for item in _list_thread_events(limit=1000)
                    if item.get("actor_id") == f"qq:user:{LIVE_SENDER_USER_ID}"
                    and token in str(item.get("content_text", ""))
                ),
                None,
            ),
            timeout=30,
            interval=1.0,
        )
        evidence["initial_event"] = initial_event

        first_run_id = str(initial_event["run_id"])
        first_run = await _wait_for(
            lambda: (
                lambda run: run if run.get("status") == "completed" else None
            )(_get_run(first_run_id)),
            timeout=60,
            interval=1.0,
        )
        evidence["first_run"] = first_run

        first_run_detail = first_run
        evidence["first_run_detail"] = first_run_detail

        first_message = await _wait_for(
            lambda: next(
                (
                    item
                    for item in _list_thread_messages(limit=1000)
                    if item.get("run_id") == first_run["run_id"] and item.get("role") == "assistant"
                ),
                None,
            ),
            timeout=30,
            interval=1.0,
        )
        evidence["first_message"] = first_message

        scheduled_event = await _wait_for(
            lambda: next(
                (
                    item
                    for item in _list_thread_events(limit=1000)
                    if item.get("raw_event", {}).get("synthetic") is True
                    and item.get("payload_json", {}).get("metadata", {}).get("source") == "scheduler"
                    and token in str(item.get("content_text", ""))
                ),
                None,
            ),
            timeout=90,
            interval=2.0,
        )
        evidence["scheduled_event"] = scheduled_event
        assert scheduled_event["payload_json"]["metadata"]["scheduled_task"]["kind"] == "conversation_wakeup"

        wake_run_id = str(scheduled_event["run_id"])
        wake_run_detail = await _wait_for(
            lambda: (
                lambda run: run if run.get("status") == "completed" else None
            )(_get_run(wake_run_id)),
            timeout=30,
            interval=1.0,
        )
        evidence["wake_run_detail"] = wake_run_detail
        assert str(wake_run_detail["metadata"].get("model_used", "")).strip()

        wake_message = await _wait_for(
            lambda: next(
                (
                    item
                    for item in _list_thread_messages(limit=1000)
                    if item.get("run_id") == wake_run_id and item.get("role") == "assistant"
                ),
                None,
            ),
            timeout=30,
            interval=1.0,
        )
        evidence["wake_message"] = wake_message
        wake_text = str(wake_message.get("content_text", ""))
        assert wake_text.strip()
        assert any(marker in wake_text for marker in ("提醒", "口令", token))

        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    finally:
        _put_session_agent(original_agent)
        _delete_live_test_scheduled_tasks()
        _restart_runtime_container()
