from pathlib import Path

from acabot.agent.response import AgentResponse
from acabot.runtime import (
    ResolvedAgent,
    ComputerPolicy,
    ComputerRuntime,
    ComputerRuntimeConfig,
    ImageContextService,
    MessagePreparationService,
    MessageProjectionService,
    MessageResolutionService,
    RouteDecision,
    RunContext,
    RunRecord,
    RuntimeModelRequest,
    ThreadState,
)
from acabot.types import EventAttachment, EventSource, MsgSegment, ReplyReference, StandardEvent


class FakeCaptionAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, object]],
        model: str | None = None,
        request_options=None,
    ) -> AgentResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
            }
        )
        return AgentResponse(text=f"caption-{len(self.calls)}", model_used=model or "")


class FakeGateway:
    def __init__(self, *, reply_image_uri: str, reply_text: str = "原消息里的图") -> None:
        self.reply_image_uri = reply_image_uri
        self.reply_text = reply_text
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_api(self, action: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append((action, dict(params)))
        assert action == "get_msg"
        return {
            "status": "ok",
            "data": {
                "message_id": params["message_id"],
                "message": [
                    {"type": "text", "data": {"text": self.reply_text}},
                    {"type": "image", "data": {"file": self.reply_image_uri}},
                ],
            },
        }


class FakeModelRegistry:
    def __init__(self) -> None:
        self.resolve_target_request_calls: list[str] = []

    def resolve_target_request(self, target_id: str) -> RuntimeModelRequest | None:
        self.resolve_target_request_calls.append(target_id)
        if target_id != "system:image_caption":
            return None
        return RuntimeModelRequest(
            provider_kind="openai_compatible",
            model="caption-model",
            supports_vision=True,
            provider_id="provider",
            preset_id="caption-model",
            provider_params={"base_url": "https://example.com"},
        )


def _ctx(tmp_path: Path, *, run_mode: str = "respond", include_reply: bool = True) -> tuple[ComputerRuntime, RunContext, Path, Path]:
    computer = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            host_skills_catalog_root_path=str(tmp_path / "workspaces/catalog/skills"),
        )
    )
    current_image = tmp_path / "current.jpg"
    current_image.write_bytes(b"current-image-bytes")
    reply_image = tmp_path / "reply.jpg"
    reply_image.write_bytes(b"reply-image-bytes")
    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": "请看这两张图"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role="member",
        reply_reference=(
            ReplyReference(message_id="msg-0", text_preview="旧图")
            if include_reply
            else None
        ),
        attachments=[
            EventAttachment(
                type="image",
                source=current_image.resolve().as_uri(),
                name="current.jpg",
                mime_type="image/jpeg",
            )
        ],
    )
    ctx = RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id=event.event_id,
            status="queued",
            started_at=123,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:group:20002",
            run_mode=run_mode,
        ),
        thread=ThreadState(
            thread_id="qq:group:20002",
            channel_scope="qq:group:20002",
        ),
        agent=ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            computer_policy=ComputerPolicy(),
            config={
                "image_caption": {
                    "enabled": True,
                    "caption_prompt": "请描述图片。",
                    "include_reply_images": include_reply,
                }
            },
        ),
        model_request=RuntimeModelRequest(
            provider_kind="openai_compatible",
            model="main-model",
            supports_vision=True,
            provider_id="provider",
            preset_id="main-model",
            provider_params={"base_url": "https://example.com"},
        ) if run_mode == "respond" else None,
    )
    return computer, ctx, current_image, reply_image


def _service(agent: FakeCaptionAgent, *, gateway, computer: ComputerRuntime, registry: FakeModelRegistry) -> MessagePreparationService:
    image_context = ImageContextService(
        agent=agent,
        model_registry_manager=registry,
    )
    return MessagePreparationService(
        resolution_service=MessageResolutionService(
            gateway=gateway,
            computer_runtime=computer,
        ),
        projection_service=MessageProjectionService(
            image_context=image_context,
        ),
    )


async def test_message_preparation_service_captions_images_and_builds_model_content(tmp_path: Path) -> None:
    computer, ctx, _current_image, reply_image = _ctx(tmp_path)
    gateway = FakeGateway(reply_image_uri=reply_image.resolve().as_uri())
    computer.gateway = gateway
    await computer.prepare_run_context(ctx)
    agent = FakeCaptionAgent()
    service = _service(
        agent,
        gateway=gateway,
        computer=computer,
        registry=FakeModelRegistry(),
    )

    await service.prepare(ctx)

    assert ctx.resolved_message is not None
    assert len(ctx.resolved_message.resolved_images) == 2
    assert {item.origin for item in ctx.resolved_message.resolved_images} == {"event", "reply"}
    assert ctx.message_projection is not None
    assert ctx.message_projection.history_text.endswith(
        "[系统补充-引用文本: 原消息里的图] [系统补充-图片说明: caption-1] [系统补充-引用图片说明: caption-2]"
    )
    content = ctx.message_projection.model_content
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert sum(1 for item in content if item["type"] == "image_url") == 2
    assert any(item.get("text") == "以下图片来自被引用消息。" for item in content if item["type"] == "text")
    assert gateway.calls[0][0] == "get_msg"
    assert len(agent.calls) == 2


async def test_message_preparation_service_record_only_uses_fallback_caption_request(tmp_path: Path) -> None:
    computer, ctx, _current_image, _reply_image = _ctx(tmp_path, run_mode="record_only", include_reply=False)
    await computer.prepare_run_context(ctx)
    agent = FakeCaptionAgent()
    registry = FakeModelRegistry()
    service = _service(
        agent,
        gateway=None,
        computer=computer,
        registry=registry,
    )

    await service.prepare(ctx)

    assert ctx.message_projection is not None
    assert ctx.message_projection.history_text.endswith("[系统补充-图片说明: caption-1]")
    assert len(ctx.resolved_images) == 1
    assert registry.resolve_target_request_calls == ["system:image_caption"]
    assert len(agent.calls) == 1


async def test_message_preparation_service_still_builds_projection_when_caption_disabled(tmp_path: Path) -> None:
    computer, ctx, _current_image, _reply_image = _ctx(tmp_path, include_reply=False)
    ctx.agent.config["image_caption"]["enabled"] = False
    await computer.prepare_run_context(ctx)
    agent = FakeCaptionAgent()
    service = _service(
        agent,
        gateway=None,
        computer=computer,
        registry=FakeModelRegistry(),
    )

    await service.prepare(ctx)

    assert ctx.resolved_message is not None
    assert ctx.message_projection is not None
    assert ctx.message_projection.history_text == "[acacia/10001] 请看这两张图 [attachments:image]"
    assert isinstance(ctx.message_projection.model_content, list)
    assert ctx.message_projection.model_content[0]["type"] == "text"
    assert ctx.message_projection.model_content[1]["type"] == "image_url"
    assert agent.calls == []
