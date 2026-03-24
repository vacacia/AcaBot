# Unified Context Assembly Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the unified context assembly flow described in [docs/todo/2026-03-23-unified-context-contribution-and-assembly-design.md](/home/acacia/AcaBot/docs/todo/2026-03-23-unified-context-contribution-and-assembly-design.md), so final model-visible context is assembled in one place and legacy prompt-slot/message-rewrite paths are removed.

**Architecture:** Add a small `context_assembly` package that owns `ContextContribution`, `AssembledContext`, `ContextAssembler`, and `PayloadJsonWriter`. Keep `RetrievalPlanner` as a prepare-only selector, move `/self` and sticky-note reads behind `MemoryBroker`, and make `ModelAgentRuntime` the only place that resolves and writes final `ctx.system_prompt` / `ctx.messages` before the agent call.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing `acabot.runtime` bootstrap/runtime contracts, file-backed sticky note and soul sources.

---

## References

- Spec: `docs/todo/2026-03-23-unified-context-contribution-and-assembly-design.md`
- Legacy discussion docs to keep nearby while deleting old paths:
  - `docs/todo/2026-03-23-context-assembler-source-map-and-final-payload.md`
  - `docs/todo/context-assembly-and-model-input.md`
- Runtime docs to update at the end:
  - `docs/05-memory-and-context.md`
  - `docs/02-runtime-mainline.md`
  - `docs/00-ai-entry.md`
  - `docs/HANDOFF.md`

## Assumptions Locked In

- No `session prompt slots` in the new design.
- No `workspace_state` injection in the new design.
- `PromptSlot` and `RetrievalPlanner.assemble()` are legacy and should be deleted, not preserved.
- `/self`, sticky note, and retrieved memory are all read behind `MemoryBroker`.
- Keep the `SoulSource` class/path for this plan, but change its managed file shape to real `/self` semantics before broker integration.
- `ctx.system_prompt` and `ctx.messages` are final outputs only.
- Current-user `model_content` replaces the legacy `apply_model_message()` rewrite path.

## File Map

**Create**

- `src/acabot/runtime/context_assembly/__init__.py`
  - Export the new context-assembly public surface.
- `src/acabot/runtime/context_assembly/contracts.py`
  - Define `ContextContribution` and `AssembledContext`.
- `src/acabot/runtime/context_assembly/assembler.py`
  - Convert runtime inputs into contributions and assemble final `system_prompt` / `messages`.
- `src/acabot/runtime/context_assembly/payload_json_writer.py`
  - Serialize final model-call payload immediately before `BaseAgent.run(...)`.
- `src/acabot/runtime/memory/file_backed/retrievers.py`
  - Add adapters that read `/self` and sticky notes as `MemoryBlock` results for `MemoryBroker`.
- `tests/runtime/test_soul_source.py`
  - Unit tests for the refactored `/self` file layout and append helper.
- `tests/runtime/test_context_assembler.py`
  - Unit tests for contribution collection and final assembly ordering.
- `tests/runtime/test_payload_json_writer.py`
  - Unit tests for JSON payload output.
- `tests/runtime/test_file_backed_memory_retrievers.py`
  - Unit tests for `/self` and sticky-note retrievers.

**Modify**

- `src/acabot/runtime/contracts/__init__.py`
  - Drop legacy `PromptSlot` re-exports when the type is deleted.
- `src/acabot/runtime/contracts/context.py`
  - Remove `PromptSlot`; remove prompt-slot storage from `RetrievalPlan` / `RunContext`; keep only prepare-time retrieval state.
- `src/acabot/runtime/model/model_agent_runtime.py`
  - Inject and use `ContextAssembler` and `PayloadJsonWriter`; stop building final prompt inline.
- `src/acabot/runtime/pipeline.py`
  - Stop assembling final messages; remove static soul injection and file-backed sticky-note injection from pipeline.
- `src/acabot/runtime/inbound/message_preparation.py`
  - Delete `apply_model_message()` and make sure `prepare()` still produces `ctx.message_projection` when image captioning is disabled.
- `src/acabot/runtime/contracts/session_config.py`
  - Remove legacy `prompt_slots` from `ContextDecision`.
- `src/acabot/runtime/control/session_runtime.py`
  - Stop parsing `prompt_slots` out of session context payloads.
- `src/acabot/runtime/soul/source.py`
  - Refactor the legacy soul source into `/self/today.md + /self/daily/*.md` while preserving temporary compatibility helpers.
- `src/acabot/runtime/memory/retrieval_planner.py`
  - Keep `prepare()` only; remove prompt-assembly config and final message assembly code.
- `src/acabot/runtime/memory/memory_broker.py`
  - Accept the new file-backed retriever composition and drop prompt-slot metadata.
- `src/acabot/runtime/bootstrap/builders.py`
  - Build `MemoryBroker` with file-backed retrievers, remove `PromptAssemblyConfig`, and add `PayloadJsonWriter` path resolution.
- `src/acabot/runtime/bootstrap/__init__.py`
  - Wire assembler and payload writer into runtime bootstrap; stop passing soul/sticky sources to pipeline for model assembly.
- `src/acabot/runtime/bootstrap/components.py`
  - Add `context_assembler` and `payload_json_writer` to `RuntimeComponents`.
- `src/acabot/runtime/__init__.py`
  - Export new context-assembly contracts and drop stale exports.
- `tests/runtime/test_model_agent_runtime.py`
  - Cover assembler/writer runtime integration.
- `tests/runtime/test_retrieval_planner.py`
  - Rewrite around `prepare()` only.
- `tests/runtime/test_pipeline_runtime.py`
  - Verify pipeline produces materials but does not assemble final prompt, and add one end-to-end mainline test for the new assembly path.
- `tests/runtime/test_memory_broker.py`
  - Verify new broker inputs and file-backed retrieval composition.
- `tests/runtime/test_image_context.py`
  - Remove `apply_model_message()` usage from image tests.
- `tests/runtime/test_session_runtime.py`
  - Verify session context no longer carries `prompt_slots`.
- `tests/runtime/test_bootstrap.py`
  - Verify bootstrap wires assembler/writer, chooses the payload JSON directory, and composes the new broker.
- `tests/test_main.py`
  - Keep the main-entry smoke tests buildable after `PromptAssemblyConfig` removal and `RuntimeComponents` shape changes.
- `docs/05-memory-and-context.md`
- `docs/02-runtime-mainline.md`
- `docs/00-ai-entry.md`
- `docs/HANDOFF.md`

---

### Task 1: Add Context-Assembly Contracts

**Files:**
- Create: `src/acabot/runtime/context_assembly/__init__.py`
- Create: `src/acabot/runtime/context_assembly/contracts.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_context_assembler.py`

- [ ] **Step 1: Write the failing contract test**

```python
from acabot.runtime.context_assembly.contracts import AssembledContext, ContextContribution


def test_context_assembly_contracts_expose_minimal_shape() -> None:
    contribution = ContextContribution(
        source_kind="sticky_note",
        target_slot="message_prefix",
        priority=800,
        role="system",
        content="用户喜欢短回答",
    )
    assembled = AssembledContext(system_prompt="You are Aca.", messages=[])

    assert contribution.target_slot == "message_prefix"
    assert assembled.system_prompt == "You are Aca."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runtime/test_context_assembler.py::test_context_assembly_contracts_expose_minimal_shape -v`
Expected: FAIL with `ModuleNotFoundError` or import failure for `acabot.runtime.context_assembly`.

- [ ] **Step 3: Write minimal contracts and exports**

```python
# src/acabot/runtime/context_assembly/contracts.py
@dataclass(slots=True)
class ContextContribution:
    source_kind: str
    target_slot: str
    priority: int
    role: str
    content: str | list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssembledContext:
    system_prompt: str
    messages: list[dict[str, Any]]
```

- [ ] **Step 4: Export the new contracts**

```python
# src/acabot/runtime/context_assembly/__init__.py
from .contracts import AssembledContext, ContextContribution

__all__ = ["AssembledContext", "ContextContribution"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/runtime/test_context_assembler.py::test_context_assembly_contracts_expose_minimal_shape -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/context_assembly/__init__.py \
  src/acabot/runtime/context_assembly/contracts.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_context_assembler.py
git commit -m "feat: add context assembly contracts"
```

---

### Task 2: Implement ContextAssembler

**Files:**
- Create: `src/acabot/runtime/context_assembly/assembler.py`
- Modify: `src/acabot/runtime/context_assembly/__init__.py`
- Test: `tests/runtime/test_context_assembler.py`

- [ ] **Step 1: Write failing assembly-order tests**

```python
async def test_context_assembler_orders_system_prompt_and_message_slots() -> None:
    ctx = _assembler_ctx(
        base_prompt="base",
        memory_blocks=[
            MemoryBlock(title="Self", content="self", metadata={"memory_type": "self_memory"}),
            MemoryBlock(title="Retrieved", content="retrieved", metadata={"memory_type": "episodic"}),
        ],
        retrieval_plan=RetrievalPlan(
            compressed_messages=[{"role": "user", "content": "older"}],
            metadata={"working_summary_text": ""},
        ),
        message_projection=MessageProjection(history_text="older", model_content="hello"),
    )
    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())

    assert assembled.system_prompt == "base"
    assert [item["content"] for item in assembled.messages] == ["self", "retrieved", "older", "hello"]
```

- [ ] **Step 2: Add failing multimodal-current-user and tool-summary tests**

```python
def test_context_assembler_keeps_model_content_shape() -> None:
    multimodal = [{"type": "text", "text": "请看图"}]
    ctx = _assembler_ctx(
        base_prompt="base",
        retrieval_plan=RetrievalPlan(compressed_messages=[]),
        message_projection=MessageProjection(history_text="请看图", model_content=multimodal),
    )
    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())
    assert assembled.messages[-1]["content"] == multimodal
```

```python
def test_context_assembler_includes_skill_and_subagent_summaries_in_system_prompt() -> None:
    tool_runtime = ToolRuntime(
        metadata={
            "visible_skill_summaries": [{"name": "memory_append", "summary": "记录新的 self 事项"}],
            "visible_subagent_summaries": [{"agent_id": "worker", "summary": "负责独立实现子任务"}],
        }
    )
    ctx = _assembler_ctx(
        base_prompt="base",
        retrieval_plan=RetrievalPlan(compressed_messages=[]),
        message_projection=MessageProjection(history_text="hello", model_content="hello"),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=tool_runtime)

    assert "memory_append" in assembled.system_prompt
    assert "worker" in assembled.system_prompt
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_context_assembler.py -v`
Expected: FAIL with `AttributeError` / missing `ContextAssembler`.

- [ ] **Step 4: Implement minimal assembler**

```python
class ContextAssembler:
    SLOT_ORDER = {
        "system_prompt": 0,
        "message_prefix": 1,
        "message_history": 2,
        "message_current_user": 3,
    }

    def assemble(self, ctx: RunContext, *, base_prompt: str, tool_runtime: ToolRuntime) -> AssembledContext:
        contributions = self._collect_contributions(
            ctx,
            base_prompt=base_prompt,
            tool_runtime=tool_runtime,
        )
        return self._assemble_contributions(contributions)

    def _assemble_contributions(self, contributions: list[ContextContribution]) -> AssembledContext:
        system_parts = [
            item.content
            for item in sorted(contributions, key=self._sort_key)
            if item.target_slot == "system_prompt"
        ]
        messages = self._build_messages(contributions)
        return AssembledContext(system_prompt="\n\n".join(str(part) for part in system_parts), messages=messages)
```

- [ ] **Step 5: Add collection helpers for current runtime inputs**

```python
def _collect_contributions(self, ctx, *, base_prompt: str, tool_runtime: ToolRuntime) -> list[ContextContribution]:
    # collect base prompt, tool reminders, memory blocks, working summary,
    # retained history, and current user model_content
    ...
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/runtime/test_context_assembler.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add \
  src/acabot/runtime/context_assembly/__init__.py \
  src/acabot/runtime/context_assembly/assembler.py \
  tests/runtime/test_context_assembler.py
git commit -m "feat: add context assembler"
```

---

### Task 3: Add PayloadJsonWriter

**Files:**
- Create: `src/acabot/runtime/context_assembly/payload_json_writer.py`
- Modify: `src/acabot/runtime/context_assembly/__init__.py`
- Test: `tests/runtime/test_payload_json_writer.py`

- [ ] **Step 1: Write the failing payload test**

```python
def test_payload_json_writer_records_final_model_payload(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runtime/test_payload_json_writer.py::test_payload_json_writer_records_final_model_payload -v`
Expected: FAIL with missing writer import/class.

- [ ] **Step 3: Implement the minimal writer**

```python
class PayloadJsonWriter:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    def write(self, *, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.root_dir / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
```

- [ ] **Step 4: Add a failing non-serializable guard test**

```python
def test_payload_json_writer_drops_executor_object(tmp_path: Path) -> None:
    writer = PayloadJsonWriter(root_dir=tmp_path)
    path = writer.write(run_id="run:1", payload={"has_tool_executor": True, "tool_executor": object()})
    assert "tool_executor" not in json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/runtime/test_payload_json_writer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/context_assembly/__init__.py \
  src/acabot/runtime/context_assembly/payload_json_writer.py \
  tests/runtime/test_payload_json_writer.py
git commit -m "feat: add payload json writer"
```

---

### Task 4: Make MessageProjection Always Available

**Files:**
- Modify: `src/acabot/runtime/inbound/message_preparation.py`
- Modify: `tests/runtime/test_image_context.py`

- [ ] **Step 1: Write the failing text-only projection test**

```python
async def test_message_preparation_service_builds_text_only_projection_when_image_caption_is_disabled(tmp_path: Path) -> None:
    service = _service(...)
    ctx = _text_only_ctx(tmp_path)
    ctx.profile.config["image_caption"] = {"enabled": False}

    await service.prepare(ctx)

    assert ctx.message_projection is not None
    assert ctx.message_projection.history_text == "[acacia/10001] hello"
    assert ctx.message_projection.model_content == "[acacia/10001] hello"
```

- [ ] **Step 2: Write the failing image test without `apply_model_message()`**

```python
async def test_message_preparation_service_captions_images_and_exposes_model_content(tmp_path: Path) -> None:
    await service.prepare(ctx)
    assert isinstance(ctx.message_projection.model_content, list)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_image_context.py -v`
Expected: FAIL because `prepare()` currently returns early when image captioning is disabled, and legacy tests still depend on `apply_model_message()`.

- [ ] **Step 4: Make `prepare()` always resolve and project the message**

```python
async def prepare(self, ctx: RunContext) -> None:
    settings = parse_image_caption_settings(ctx.profile.config.get("image_caption"))
    resolved = await self.resolution_service.resolve(
        ctx,
        include_reply_images=settings.include_reply_images,
    )
    await self.projection_service.project(
        ctx,
        resolved=resolved,
        image_settings=settings,
    )
```

- [ ] **Step 5: Delete `apply_model_message()`**

```python
class MessagePreparationService:
    async def prepare(self, ctx: RunContext) -> None:
        ...
    # remove apply_model_message()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/runtime/test_image_context.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add \
  src/acabot/runtime/inbound/message_preparation.py \
  tests/runtime/test_image_context.py
git commit -m "refactor: always build message projection"
```

---

### Task 5: Route ModelAgentRuntime Through the Assembler

**Files:**
- Modify: `src/acabot/runtime/model/model_agent_runtime.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_model_agent_runtime.py`

- [ ] **Step 1: Write the failing runtime integration test**

```python
async def test_model_agent_runtime_assembles_context_before_agent_call() -> None:
    ctx = _context()
    ctx.retrieval_plan = RetrievalPlan(
        compressed_messages=[{"role": "user", "content": "older"}],
        metadata={"working_summary_text": "summary"},
    )
    ctx.message_projection = MessageProjection(
        history_text="older",
        model_content="hello",
    )
    ctx.memory_blocks = [
        MemoryBlock(
            title="Sticky",
            content="用户喜欢简洁回答",
            scope="user",
            metadata={"memory_type": "sticky_note"},
        )
    ]

    runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        context_assembler=ContextAssembler(),
        payload_json_writer=FakeWriter(),
    )

    await runtime.execute(ctx)

    assert ctx.system_prompt == "You are Aca."
    assert [item["content"] for item in ctx.messages] == ["用户喜欢简洁回答", "summary", "older", "hello"]
```

- [ ] **Step 2: Add a failing “skip write on early return” test**

```python
async def test_model_agent_runtime_does_not_write_payload_when_capability_check_fails() -> None:
    ...
    assert writer.calls == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_model_agent_runtime.py -v`
Expected: FAIL because `ModelAgentRuntime` has no assembler/writer integration.

- [ ] **Step 4: Unify the `ContextAssembler` public API**

```python
class ContextAssembler:
    def assemble(self, ctx: RunContext, *, base_prompt: str, tool_runtime: ToolRuntime) -> AssembledContext:
        contributions = self._collect_contributions(ctx, base_prompt=base_prompt, tool_runtime=tool_runtime)
        return self._assemble_contributions(contributions)
```

- [ ] **Step 5: Inject assembler and writer into runtime**

```python
class ModelAgentRuntime(AgentRuntime):
    def __init__(..., context_assembler: ContextAssembler | None = None, payload_json_writer: PayloadJsonWriter | None = None):
        self.context_assembler = context_assembler or ContextAssembler()
        self.payload_json_writer = payload_json_writer
```

- [ ] **Step 6: Replace inline `_build_system_prompt(...)` usage**

```python
assembled = self.context_assembler.assemble(
    ctx,
    base_prompt=self.prompt_loader.load(ctx.profile.prompt_ref),
    tool_runtime=tool_runtime,
)
ctx.system_prompt = assembled.system_prompt
ctx.messages = assembled.messages
```

- [ ] **Step 7: Write payload JSON immediately before `agent.run(...)`**

```python
if self.payload_json_writer is not None:
    self.payload_json_writer.write(run_id=ctx.run.run_id, payload=payload_dict)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/runtime/test_model_agent_runtime.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add \
  src/acabot/runtime/model/model_agent_runtime.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_model_agent_runtime.py
git commit -m "refactor: route model runtime through context assembler"
```

---

### Task 6: Remove Session `prompt_slots` From the Runtime Contract

**Files:**
- Modify: `src/acabot/runtime/contracts/session_config.py`
- Modify: `src/acabot/runtime/control/session_runtime.py`
- Test: `tests/runtime/test_session_runtime.py`

- [ ] **Step 1: Write the failing session context test**

```python
def test_session_runtime_context_decision_no_longer_exposes_prompt_slots(tmp_path: Path) -> None:
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    decision = runtime.resolve_context(facts, session, surface)
    assert not hasattr(decision, "prompt_slots")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/runtime/test_session_runtime.py::test_session_runtime_context_decision_no_longer_exposes_prompt_slots -v`
Expected: FAIL because `ContextDecision` still carries `prompt_slots`.

- [ ] **Step 3: Remove `prompt_slots` from `ContextDecision`**

```python
@dataclass(slots=True)
class ContextDecision:
    sticky_note_scopes: list[str] = field(default_factory=list)
    retrieval_tags: list[str] = field(default_factory=list)
    context_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Stop parsing `prompt_slots` in `SessionRuntime.resolve_context()`**

```python
return ContextDecision(
    sticky_note_scopes=list(payload.get("sticky_note_scopes", [])),
    retrieval_tags=list(payload.get("retrieval_tags", [])),
    context_labels=list(payload.get("context_labels", [])),
    notes=list(payload.get("notes", [])),
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/runtime/test_session_runtime.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/contracts/session_config.py \
  src/acabot/runtime/control/session_runtime.py \
  tests/runtime/test_session_runtime.py
git commit -m "refactor: remove session prompt slot support"
```

---

### Task 7: Strip RetrievalPlanner Down to Prepare-Only and Update Callers

**Files:**
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/contracts/context.py`
- Modify: `src/acabot/runtime/memory/retrieval_planner.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_retrieval_planner.py`
- Test: `tests/runtime/test_pipeline_runtime.py`

- [ ] **Step 1: Write failing tests that only assert `prepare()` outputs**

```python
def test_retrieval_planner_prepare_keeps_summary_and_retained_history() -> None:
    plan = planner.prepare(ctx)
    assert plan.compressed_messages[-1]["content"] == "u3"
    assert plan.metadata["working_summary_text"] == ""
```

- [ ] **Step 2: Write failing tests that legacy `assemble()` and `PromptAssemblyConfig` are gone**

```python
def test_retrieval_planner_no_longer_exposes_assemble() -> None:
    assert not hasattr(planner, "assemble")
```

```python
def test_pipeline_runtime_no_longer_constructs_prompt_assembly_config() -> None:
    pipeline = ThreadPipeline(..., retrieval_planner=RetrievalPlanner())
    assert pipeline.retrieval_planner is not None
```

```python
async def test_thread_pipeline_leaves_ctx_messages_for_model_runtime_only() -> None:
    class InspectingAgentRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.captured_messages = []

        async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
            self.captured_messages = list(ctx.messages)
            return AgentRuntimeResult(status="completed", text="ok")

    agent_runtime = InspectingAgentRuntime()
    await pipeline.execute(ctx)

    assert ctx.retrieval_plan is not None
    assert agent_runtime.captured_messages == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_retrieval_planner.py tests/runtime/test_pipeline_runtime.py -v`
Expected: FAIL because the current planner and callers still depend on prompt-assembly behavior.

- [ ] **Step 4: Delete `PromptSlot` and remove `ctx.prompt_slots` from runtime contracts**

```python
@dataclass(slots=True)
class RetrievalPlan:
    requested_tags: list[str] = field(default_factory=list)
    sticky_note_scopes: list[str] = field(default_factory=list)
    retained_history: list[dict[str, Any]] = field(default_factory=list)
    dropped_messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass(slots=True)
class RunContext:
    ...
    retrieval_plan: RetrievalPlan | None = None
    memory_blocks: list["MemoryBlock"] = field(default_factory=list)
    # remove prompt_slots
```

- [ ] **Step 5: Clean up contract exports and remove `PromptAssemblyConfig` / `assemble()`**

```python
# src/acabot/runtime/contracts/__init__.py
# remove PromptSlot from imports and __all__

class RetrievalPlanner:
    def __init__(self) -> None:
        ...

    def prepare(self, ctx: RunContext) -> RetrievalPlan:
        ...
```

- [ ] **Step 6: Update builder and pipeline callers, and stop `ThreadPipeline` from mutating final `ctx.messages`**

```python
def build_retrieval_planner(config: Config) -> RetrievalPlanner:
    return RetrievalPlanner()
```

```python
# src/acabot/runtime/pipeline.py
if self.retrieval_planner is not None:
    ctx.retrieval_plan = self.retrieval_planner.prepare(ctx)
# do not copy compressed messages into ctx.messages here

ctx.memory_blocks = await self.memory_broker.retrieve(ctx) if self.memory_broker is not None else []
# do not call planner.assemble(...) or _inject_memory_blocks(...) here
```

```python
# tests/runtime/test_pipeline_runtime.py
pipeline = ThreadPipeline(..., retrieval_planner=RetrievalPlanner())
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/runtime/test_retrieval_planner.py tests/runtime/test_pipeline_runtime.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add \
  src/acabot/runtime/contracts/__init__.py \
  src/acabot/runtime/contracts/context.py \
  src/acabot/runtime/memory/retrieval_planner.py \
  src/acabot/runtime/bootstrap/builders.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_retrieval_planner.py \
  tests/runtime/test_pipeline_runtime.py
git commit -m "refactor: reduce retrieval planner to prepare-only"
```

---
### Task 7.5: 重构 self

**Files:**
- Modify: `src/acabot/runtime/soul/source.py`
- Test: `tests/runtime/test_soul_source.py`

- [ ] **Step 1: Write the failing `/self` layout test**

```python
def test_soul_source_initializes_self_layout_instead_of_legacy_core_files(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)

    assert source.list_files()[0]["name"] == "today.md"
    assert (tmp_path / "today.md").exists()
    assert (tmp_path / "daily").is_dir()
    assert not (tmp_path / "identity.md").exists()
```

- [ ] **Step 2: Write the failing append-and-render test**

```python
def test_soul_source_appends_today_and_renders_recent_self_context(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)

    source.append_today_entry("[qq:group:123 time=1] vi 交代了部署任务")
    source.write_file("daily/2026-03-23.md", "# 2026-03-23\n- 完成部署")

    rendered = source.build_recent_context_text(max_daily_files=1)

    assert "today.md" in rendered
    assert "daily/2026-03-23.md" in rendered
    assert "部署任务" in rendered
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_soul_source.py -v`
Expected: FAIL because `SoulSource` still initializes `identity.md / soul.md / state.yaml / task.md`, rejects nested `daily/...` names, and does not expose `append_today_entry()` / `build_recent_context_text()`.

- [ ] **Step 4: Refactor `SoulSource` into `/self` layout while keeping transition compatibility**

```python
class SoulSource:
    TODAY_FILE = "today.md"
    DAILY_DIR = "daily"

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_self_layout()

    def append_today_entry(self, line: str) -> dict[str, Any]:
        normalized = str(line or "").strip()
        if not normalized:
            raise ValueError("today entry cannot be empty")
        path = self.root_dir / self.TODAY_FILE
        existing = path.read_text(encoding="utf-8").rstrip()
        content = f"{existing}\n{normalized}\n" if existing else f"{normalized}\n"
        path.write_text(content, encoding="utf-8")
        return self.read_file(self.TODAY_FILE)

    def build_recent_context_text(self, *, max_daily_files: int = 2) -> str:
        sections = [self._render_relative_file(self.TODAY_FILE)]
        for path in self._recent_daily_files(limit=max_daily_files):
            sections.append(self._render_relative_file(f"{self.DAILY_DIR}/{path.name}"))
        return "\n\n".join(section for section in sections if section).strip()

    def build_prompt_text(self) -> str:
        # Temporary compatibility bridge for the legacy soul injection path.
        return self.build_recent_context_text()
```

- [ ] **Step 5: Allow `daily/*.md` relative paths and list them as `/self` files**

```python
def _resolve_name(self, name: str) -> Path:
    normalized = str(name or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("."):
        raise ValueError("self file name cannot be empty")
    path = (self.root_dir / normalized).resolve()
    try:
        path.relative_to(self.root_dir)
    except ValueError as exc:
        raise ValueError("invalid self file path") from exc
    return path

def list_files(self) -> list[dict[str, Any]]:
    items = [self._to_item(path=self.root_dir / self.TODAY_FILE, name=self.TODAY_FILE, is_core=True)]
    for path in sorted((self.root_dir / self.DAILY_DIR).glob("*.md"), reverse=True):
        items.append(self._to_item(path=path, name=f"{self.DAILY_DIR}/{path.name}", is_core=False))
    return items
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/runtime/test_soul_source.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add \
  src/acabot/runtime/soul/source.py \
  tests/runtime/test_soul_source.py
git commit -m "refactor: reshape soul source into self layout"
```

### Task 8: Move `/self` and Sticky Notes Behind MemoryBroker

**Files:**
- Create: `src/acabot/runtime/memory/file_backed/retrievers.py`
- Modify: `src/acabot/runtime/memory/memory_broker.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/pipeline.py`
- Test: `tests/runtime/test_file_backed_memory_retrievers.py`
- Test: `tests/runtime/test_memory_broker.py`
- Test: `tests/runtime/test_bootstrap.py`

- [ ] **Step 1: Write the failing `/self` retriever test**

```python
def test_self_file_retriever_returns_self_memory_block(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)
    retriever = SelfFileRetriever(source)
    blocks = asyncio.run(retriever(request))
    assert blocks[0].metadata["memory_type"] == "self_memory"
```

- [ ] **Step 2: Write the failing sticky-note retriever test**

```python
def test_sticky_notes_file_retriever_returns_scoped_blocks(tmp_path: Path) -> None:
    source = StickyNotesSource(root_dir=tmp_path)
    ...
    assert blocks[0].metadata["memory_type"] == "sticky_note"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/runtime/test_file_backed_memory_retrievers.py tests/runtime/test_memory_broker.py -v`
Expected: FAIL with missing retriever adapters / broker composition.

- [ ] **Step 4: Implement file-backed retriever adapters**

```python
class SelfFileRetriever:
    async def __call__(self, request) -> list[MemoryBlock]:
        return [
            MemoryBlock(
                title="Self",
                content=self.source.build_recent_context_text(),
                scope="global",
                metadata={"memory_type": "self_memory"},
            )
        ]


class StickyNotesFileRetriever:
    async def __call__(self, request) -> list[MemoryBlock]:
        ...
```

- [ ] **Step 5: Compose them behind `MemoryBroker` and the bootstrap builder**

```python
class CompositeMemoryRetriever:
    async def __call__(self, request) -> list[MemoryBlock]:
        ...
```

```python
def build_memory_broker(
    config: Config,
    *,
    memory_store: MemoryStore,
    soul_source: SoulSource,
    sticky_notes_source: StickyNotesSource,
) -> MemoryBroker:
    return MemoryBroker(
        retriever=CompositeMemoryRetriever(
            [
                SelfFileRetriever(soul_source),
                StickyNotesFileRetriever(sticky_notes_source),
                StoreBackedMemoryRetriever(memory_store),
            ]
        ),
        extractor=StructuredMemoryExtractor(memory_store),
    )
```

- [ ] **Step 6: Remove file-backed sticky/soul prompt injection from `ThreadPipeline`**

```python
# delete _prepare_static_context()
# delete _collect_sticky_blocks_from_files()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/runtime/test_file_backed_memory_retrievers.py tests/runtime/test_memory_broker.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add \
  src/acabot/runtime/memory/file_backed/retrievers.py \
  src/acabot/runtime/memory/memory_broker.py \
  src/acabot/runtime/bootstrap/builders.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/pipeline.py \
  tests/runtime/test_file_backed_memory_retrievers.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_bootstrap.py
git commit -m "feat: move self and sticky note reads behind memory broker"
```

---

### Task 9: Wire Bootstrap and Add End-to-End Mainline Regression

**Files:**
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `tests/runtime/test_bootstrap.py`
- Modify: `tests/runtime/test_pipeline_runtime.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write the failing bootstrap wiring test**

```python
async def test_build_runtime_components_wires_context_assembler_and_payload_writer(tmp_path: Path) -> None:
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    assert components.context_assembler is not None
    assert components.payload_json_writer is not None
```

- [ ] **Step 2: Write the failing payload-dir test**

```python
def test_build_runtime_components_uses_default_payload_json_dir(tmp_path: Path) -> None:
    writer = build_payload_json_writer(config)
    assert writer.root_dir == resolve_runtime_path(config, "debug/model-payloads")
```

- [ ] **Step 3: Write the failing end-to-end mainline test**

```python
async def test_pipeline_and_model_runtime_produce_final_context_and_payload_json(tmp_path: Path) -> None:
    writer = components.payload_json_writer
    await pipeline.execute(ctx)
    assert ctx.system_prompt == "You are Aca."
    assert ctx.messages[-1]["role"] == "user"
    assert any(path.suffix == ".json" for path in writer.root_dir.iterdir())
```

- [ ] **Step 4: Write the failing `RuntimeComponents` main smoke test**

```python
def test_runtime_components_fixture_matches_bootstrap_contract() -> None:
    components = _runtime_components_for_main_test(app=None)

    assert components.context_assembler is not None
    assert components.payload_json_writer is not None
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/runtime/test_bootstrap.py tests/runtime/test_pipeline_runtime.py tests/test_main.py -v`
Expected: FAIL because bootstrap does not yet wire the assembler/writer or choose the payload directory.

- [ ] **Step 6: Add a bootstrap builder for the payload writer**

```python
def build_payload_json_writer(config: Config) -> PayloadJsonWriter:
    runtime_conf = config.get("runtime", {})
    root_dir = resolve_runtime_path(
        config,
        runtime_conf.get("payload_json_dir", "debug/model-payloads"),
    )
    return PayloadJsonWriter(root_dir=root_dir)
```

- [ ] **Step 7: Wire assembler and writer through bootstrap**

```python
runtime_context_assembler = ContextAssembler()
runtime_payload_json_writer = build_payload_json_writer(config)

agent_runtime = ModelAgentRuntime(
    agent=agent,
    prompt_loader=prompt_loader,
    tool_runtime_resolver=runtime_tool_broker.build_tool_runtime,
    context_assembler=runtime_context_assembler,
    payload_json_writer=runtime_payload_json_writer,
)
```

- [ ] **Step 8: Add the new objects to `RuntimeComponents` and update main smoke fixtures**

```python
@dataclass(slots=True)
class RuntimeComponents:
    ...
    context_assembler: ContextAssembler
    payload_json_writer: PayloadJsonWriter
```

```python
# tests/test_main.py
return RuntimeComponents(
    ...,
    retrieval_planner=RetrievalPlanner(),
    context_assembler=ContextAssembler(),
    payload_json_writer=PayloadJsonWriter(root_dir=Path("/tmp/acabot-test-payloads")),
)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/runtime/test_bootstrap.py tests/runtime/test_pipeline_runtime.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add \
  src/acabot/runtime/bootstrap/builders.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/bootstrap/components.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/test_main.py
git commit -m "feat: wire unified context assembly into bootstrap"
```

---

### Task 10: Sync Public Docs and Runtime Handoff Notes

**Files:**
- Modify: `docs/05-memory-and-context.md`
- Modify: `docs/02-runtime-mainline.md`
- Modify: `docs/00-ai-entry.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: Write the doc diff checklist**

```markdown
- context assembly now lives in `ContextAssembler`
- retrieval planner is prepare-only
- memory broker owns `/self`, sticky note, and retrieved memory reads
- `ctx.system_prompt` / `ctx.messages` are final outputs only
- session no longer provides a generic prompt-slot injection path
```

- [ ] **Step 2: Update memory/context architecture doc**

Runbook target: `docs/05-memory-and-context.md`
Expected change: describe `retained_history`, `working_summary`, `ContextContribution`, and broker-owned file-backed memory reads.

- [ ] **Step 3: Update runtime mainline doc**

Runbook target: `docs/02-runtime-mainline.md`
Expected change: replace legacy prompt-slot assembly flow with `ContextAssembler -> PayloadJsonWriter -> BaseAgent.run(...)`.

- [ ] **Step 4: Update entry doc and handoff**

Runbook targets:
- `docs/00-ai-entry.md`
- `docs/HANDOFF.md`

Expected change:
- entry doc names the new context assembly center
- handoff records what moved, what was deleted, and what old docs are now stale

- [ ] **Step 5: Run the targeted regression suite**

Run: `pytest tests/runtime/test_context_assembler.py tests/runtime/test_payload_json_writer.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_retrieval_planner.py tests/runtime/test_soul_source.py tests/runtime/test_file_backed_memory_retrievers.py tests/runtime/test_memory_broker.py tests/runtime/test_bootstrap.py tests/runtime/test_image_context.py tests/runtime/test_session_runtime.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  docs/05-memory-and-context.md \
  docs/02-runtime-mainline.md \
  docs/00-ai-entry.md \
  docs/HANDOFF.md
git commit -m "docs: sync unified context assembly design"
```

---

## Final Verification Checklist

- [ ] `tests/runtime/test_context_assembler.py -v`
- [ ] `tests/runtime/test_payload_json_writer.py -v`
- [ ] `tests/runtime/test_model_agent_runtime.py -v`
- [ ] `tests/runtime/test_pipeline_runtime.py -v`
- [ ] `tests/runtime/test_retrieval_planner.py -v`
- [ ] `tests/runtime/test_soul_source.py -v`
- [ ] `tests/runtime/test_file_backed_memory_retrievers.py -v`
- [ ] `tests/runtime/test_memory_broker.py -v`
- [ ] `tests/runtime/test_bootstrap.py -v`
- [ ] `tests/runtime/test_image_context.py -v`
- [ ] `tests/runtime/test_session_runtime.py -v`
- [ ] `tests/test_main.py -v`

## Notes for the Implementer

- Do not preserve `PromptSlot` as a compatibility shim. Delete it.
- Do not keep `apply_model_message()` around as dead code. Delete it.
- Do not leave `ThreadPipeline` assembling final prompt fragments. That logic belongs in `ContextAssembler`.
- Do not route session-side `prompt_slots` back into the new design.
- Keep the public `ContextAssembler` API to a single entrypoint: `assemble(ctx, *, base_prompt, tool_runtime)`.
- Land the bootstrap wiring only after the assembler, message projection, retrieval-planner cleanup, and broker composition are already passing in isolation.

Plan complete and saved to `docs/superpowers/plans/2026-03-24-unified-context-assembly.md`. Ready to execute?
