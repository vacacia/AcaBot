"""PayloadJsonWriter 测试."""

from __future__ import annotations

import json
from pathlib import Path

from acabot.runtime.context_assembly import PayloadJsonWriter


def test_payload_json_writer_records_final_model_payload(tmp_path: Path) -> None:
    """writer 应该把最终模型 payload 写成 json 文件."""

    writer = PayloadJsonWriter(root_dir=tmp_path)

    path = writer.write(
        run_id="run:1",
        payload={
            "model": "test-model",
            "system_prompt": "You are Aca.",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "has_tool_executor": False,
        },
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "test-model"
    assert data["messages"][0]["content"] == "hello"


def test_payload_json_writer_drops_executor_object(tmp_path: Path) -> None:
    """writer 不应该把不可序列化的 executor 对象直接写进 json."""

    writer = PayloadJsonWriter(root_dir=tmp_path)

    path = writer.write(
        run_id="run:1",
        payload={
            "has_tool_executor": True,
            "tool_executor": object(),
        },
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "tool_executor" not in data
