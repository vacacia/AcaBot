# AcaBot External Integrations

## Messaging Gateway: QQ via NapCat / OneBot v11

**Primary integration.** The bot communicates with QQ users through NapCat, a QQ protocol bridge implementing OneBot v11.

| Aspect | Detail |
|---|---|
| Protocol | OneBot v11 Reverse WebSocket |
| Transport | NapCat connects to AcaBot's WS server (not the other way around) |
| Default port | `8080` |
| Auth | Optional `Bearer` token via `Authorization` header |
| Implementation | `src/acabot/gateway/napcat.py` (`NapCatGateway`) |
| Message format | `src/acabot/gateway/onebot_message.py` |
| Base class | `src/acabot/gateway/base.py` (`BaseGateway`) |

### Inbound Events (QQ -> Bot)

- `message` (private/group text, images, files, audio, video, replies, @mentions)
- `poke`, `recall`, `member_join`, `member_leave`, `admin_change`, `file_upload`, `friend_added`, `mute_change`, `lucky_king`, `honor_change`, `title_change`

### Outbound Actions (Bot -> QQ)

- `send_group_msg` / `send_private_msg` (text + segments, reply-to)
- `delete_msg` (recall)
- `set_group_ban` / `set_group_kick` (moderation)
- Generic `call_api()` for any OneBot v11 endpoint

### NapCat Query Tools (`src/acabot/runtime/plugins/napcat_tools.py`)

Exposed as LLM function-calling tools via `NapCatToolsPlugin`:

| Tool | OneBot API |
|---|---|
| `get_user_info` | `get_stranger_info` |
| `get_group_info` | `get_group_info` |
| `get_group_member_info` | `get_group_member_info` |
| `get_group_member_list` | `get_group_member_list` |
| `get_message` | `get_msg` |

Avatar URL fallback: `https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640`

## LLM Providers via litellm

All LLM calls go through `litellm.acompletion` (`src/acabot/agent/agent.py`) and `litellm.aembedding` (`src/acabot/runtime/model/model_embedding_runtime.py`), which act as universal adapters. The model registry (`src/acabot/runtime/model/model_registry.py`) maps internal targets to provider-specific models.

### Registered Provider Kinds

| Kind | litellm Prefix | Default Base URL | Protocol |
|---|---|---|---|
| `openai_compatible` | `openai/` | (user-supplied) | OpenAI |
| `deepseek` | `deepseek/` | `https://api.deepseek.com` | OpenAI |
| `groq` | `groq/` | `https://api.groq.com/openai/v1` | OpenAI |
| `moonshot` | `openai/` | `https://api.moonshot.cn/v1` | OpenAI |
| `ollama` | `ollama/` | `http://localhost:11434` | OpenAI |
| `together_ai` | `together_ai/` | `https://api.together.xyz/v1` | OpenAI |
| `openrouter` | `openrouter/` | `https://openrouter.ai/api/v1` | OpenAI |
| `mistral` | `mistral/` | `https://api.mistral.ai/v1` | OpenAI |
| `fireworks_ai` | `fireworks_ai/` | `https://api.fireworks.ai/inference/v1` | OpenAI |
| `perplexity` | `perplexity/` | `https://api.perplexity.ai` | OpenAI |
| `cohere` | `cohere_chat/` | `https://api.cohere.com/v2` | OpenAI |
| `xai` | `xai/` | `https://api.x.ai/v1` | OpenAI |
| `volcengine` | `volcengine/` | `https://ark.cn-beijing.volces.com/api/v3` | OpenAI |
| `zhipu` | `openai/` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI |
| `siliconflow` | `openai/` | `https://api.siliconflow.cn/v1` | OpenAI |
| `azure` | `azure/` | (user-supplied) | OpenAI |
| `anthropic` | `anthropic/` | `https://api.anthropic.com` | Anthropic |
| `google_gemini` | `gemini/` | (Google default) | Google Gemini |

### Model Target System

Internal task slots that bind to providers at runtime:

| Target | Purpose | Client |
|---|---|---|
| `session:main_chat` | Primary conversation model | Agent run loop |
| `system:ltm_extract` | Long-term memory extraction | `LtmExtractorClient` (`src/acabot/runtime/memory/long_term_memory/model_clients.py`) |
| `system:ltm_embed` | Text embedding for LTM | `LtmEmbeddingClient` (same file) |
| `system:ltm_query_plan` | Retrieval query planning | `LtmQueryPlannerClient` (same file) |
| `system:context_compact` | Context summarization | `ContextCompactor` (`src/acabot/runtime/memory/context_compactor.py`) |
| `system:image_caption` | Image description | `src/acabot/runtime/inbound/image_context.py` |

### Authentication

- Per-provider API keys stored in `runtime_config/models/providers/*.yaml`
- Keys can be inlined or referenced via env var name (e.g., `OPENAI_API_KEY`)
- litellm auto-reads standard env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)

## Databases

### SQLite (primary persistence)

- Path: `db/acabot.db` (configurable via `runtime.persistence.sqlite_path`)
- Implementation: `src/acabot/runtime/storage/sqlite_stores.py`
- Uses synchronous `sqlite3` with `asyncio.Lock`, WAL mode, `PRAGMA synchronous=NORMAL`

| Store | Table(s) | Purpose |
|---|---|---|
| `SQLiteThreadStore` | `threads` | Conversation thread state (working messages, summary) |
| `SQLiteChannelEventStore` | `channel_events` | Full event audit log (inbound + outbound) |
| `SQLiteMessageStore` | `messages` | Normalized message records |
| `SQLiteRunStore` | `runs`, `run_steps` | Agent execution runs + step audit trail |

In-memory fallback stores exist for when SQLite persistence is not configured.

### LanceDB (long-term memory)

- Columnar vector database for structured + semantic memory
- Implementation: `src/acabot/runtime/memory/long_term_memory/storage.py` (`LanceDbLongTermMemoryStore`)
- Stored on disk under `runtime_data/` directory

| Table | Purpose |
|---|---|
| `memory_entries` | Long-term memory facts with FTS index on `lexical_text` and optional vector column |
| `thread_cursors` | Write cursor tracking per thread |
| `failed_windows` | Failed extraction windows for retry |

Retrieval modes: keyword (FTS), semantic (cosine similarity on vectors), structured (persons/entities/location/time filtering).

## Reference System (Knowledge Base)

### Local Reference Backend

- Implementation: `src/acabot/runtime/references/local.py`
- Simple file-based document storage

### OpenViking Reference Backend

- Implementation: `src/acabot/runtime/references/openviking.py` (`OpenVikingReferenceBackend`)
- Integrates with `openviking.service.OpenVikingService` (optional dependency)
- Modes: `embedded` (in-process) or `http` (remote service)
- Capabilities: document ingestion, semantic search, full/overview/abstract reading
- URI scheme: `viking://resources/acabot/{tenant_id}/{mode}/{space_id}`
- Tools exposed via `src/acabot/runtime/plugins/reference_tools.py`

## WebUI / HTTP Control Plane

- Implementation: `src/acabot/runtime/control/http_api.py` (`RuntimeHttpApiServer`)
- Built on Python stdlib `http.server.ThreadingHTTPServer`
- Default port: `8765`
- CORS origins: configurable (defaults `http://127.0.0.1:5173`, `http://localhost:5173`)
- Serves pre-built Vue SPA from `src/acabot/webui/`
- Vite dev proxy: `/api` -> `http://127.0.0.1:8765` (`webui/vite.config.ts`)

### API Surface

Provides REST-like endpoints for:
- Session management (list, create, configure, snapshot)
- Model provider/preset/binding CRUD
- Prompt management
- Thread & run inspection
- Long-term memory browsing/editing
- Reference document management
- Workspace file operations
- Log streaming

## Docker / Container Integration

### Docker Sandbox Backend (`src/acabot/runtime/computer/backends.py`)

- `DockerSandboxBackend` creates per-thread containers for isolated code execution
- Container naming: `acabot-{sha256(thread_id)[:16]}`
- Mounts workspace directory as `/workspace`
- Configurable: image, network mode
- Lifecycle: auto-create on first exec, manual stop via control plane

### Docker Compose (`deploy/compose.yaml`)

- `acabot` service: built from `Dockerfile`, ports `8080` + `8765`
- `napcat` service: `mlikiowa/napcat-docker:latest`, port `6099` (WebUI for QQ login)
- Shared bridge network `acabot_network`

## Plugin System

- Manager: `src/acabot/runtime/plugin_manager.py`
- Plugins register tools, hooks, and middleware into the runtime

### Built-in Plugins

| Plugin | Path | Function |
|---|---|---|
| `OpsControlPlugin` | `src/acabot/runtime/plugins/ops_control.py` | Slash-command control interface (e.g., `/reload`) |
| `NapCatToolsPlugin` | `src/acabot/runtime/plugins/napcat_tools.py` | QQ query tools for LLM |
| `ReferenceToolsPlugin` | `src/acabot/runtime/plugins/reference_tools.py` | Knowledge base search/read tools |
| `BackendBridgeToolPlugin` | `src/acabot/runtime/plugins/backend_bridge_tool.py` | Multi-backend persona bridging |

### Extension Plugins

- Directory: `extensions/plugins/` (loaded via `PYTHONPATH`)

## Built-in Tool Categories

### Computer Tools (`src/acabot/runtime/builtin_tools/computer.py`)

- File read/write, directory listing
- Shell command execution (one-shot or persistent session)
- Workspace management

### Skills System (`src/acabot/runtime/skills/`)

- Dynamic skill loading from `extensions/skills/`
- Skill catalog and package management
- Tools: `src/acabot/runtime/builtin_tools/skills.py`

### Sub-agent System (`src/acabot/runtime/subagents/`)

- Delegate tasks to specialized sub-agents
- Catalog, loader, execution broker
- Tools: `src/acabot/runtime/builtin_tools/subagents.py`

### Sticky Notes (`src/acabot/runtime/builtin_tools/sticky_notes.py`)

- Persistent per-session notes injected into system prompt
- File-backed: `src/acabot/runtime/memory/file_backed/sticky_notes.py`

## External Services (Runtime)

| Service | URL Pattern | Usage |
|---|---|---|
| QQ Avatar CDN | `https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640` | User avatar resolution |
| NapCat Docker | `mlikiowa/napcat-docker:latest` | QQ protocol bridge |
| Various LLM APIs | See provider table above | All LLM inference |
| OpenViking | Embedded or HTTP | Optional knowledge base backend |

## Webhooks

No outbound webhook integrations. Inbound events arrive exclusively via the NapCat reverse-WebSocket connection.
