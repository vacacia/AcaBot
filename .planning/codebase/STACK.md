# AcaBot Technology Stack

## Languages

| Language | Usage | Files |
|---|---|---|
| Python 3.11+ | Backend core, agent runtime, gateway, plugins | `src/acabot/**/*.py` |
| TypeScript | WebUI frontend | `webui/src/**/*.ts` |
| YAML | Configuration (runtime config, model providers, sessions) | `config.example.yaml`, `runtime_config/**/*.yaml` |
| SQL (SQLite DDL) | Inline schema definitions in Python | `src/acabot/runtime/storage/sqlite_stores.py` |

## Runtime

- **Python >= 3.11** (`pyproject.toml` `requires-python`)
- **Node.js LTS** (installed in `Dockerfile` for Playwright / WebUI build)
- **asyncio** event loop throughout (`asyncio.run()` in `src/acabot/main.py`)
- Entrypoint: `python -m acabot.main` (registered as `acabot` console script)

## Frameworks & Core Libraries

### Python Dependencies (from `pyproject.toml`)

| Package | Version | Purpose |
|---|---|---|
| `websockets` | >= 12.0 | Reverse-WebSocket server for NapCat/OneBot v11 gateway (`src/acabot/gateway/napcat.py`) |
| `litellm` | >= 1.40.0 | Universal LLM proxy; routes to 20+ providers via `acompletion` (`src/acabot/agent/agent.py`) |
| `aiosqlite` | >= 0.20.0 | Listed dep (actual stores use synchronous `sqlite3` with `asyncio.Lock`) |
| `pyyaml` | >= 6.0 | Config & model registry YAML parsing (`src/acabot/runtime/model/model_registry.py`) |
| `python-dotenv` | >= 1.0.0 | `.env` file loading at startup (`src/acabot/main.py`) |
| `lancedb` | >= 0.25.0 | Columnar vector store for long-term memory (`src/acabot/runtime/memory/long_term_memory/storage.py`) |
| `pyarrow` | >= 18.0.0 | Arrow schema definitions for LanceDB tables |

### Python Dev Dependencies

| Package | Version | Purpose |
|---|---|---|
| `pytest` | >= 8.0 | Test runner |
| `pytest-asyncio` | >= 0.23 | Async test support |

### Dockerfile-only Libraries (not in `pyproject.toml`)

Installed in `Dockerfile` (full image) for bot tool execution at runtime:

| Package | Purpose |
|---|---|
| `httpx`, `beautifulsoup4`, `lxml` | HTTP requests & HTML parsing |
| `Pillow` | Image processing |
| `markdown-it-py`, `Jinja2` | Markdown rendering, templating |
| `pandas`, `openpyxl` | Tabular data & Excel |
| `matplotlib`, `seaborn` | Charting |
| `weasyprint` | HTML-to-PDF |
| `yt-dlp` | Media download |
| `numpy`, `scipy` | Numeric/scientific computing |
| `playwright` + Chromium | Headless browser automation |

### Frontend (from `webui/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `vue` | ^3.5.22 | UI framework |
| `vue-router` | ^4.5.1 | Client-side routing |
| `vite` | ^7.1.7 | Dev server & build tool |
| `typescript` | ^5.9.2 | Type checking |
| `@vitejs/plugin-vue` | ^6.0.1 | Vue SFC compilation |

Built assets served from `src/acabot/webui/` (pre-built) via the HTTP API server.

## System-Level Tools (Dockerfile)

Installed in the full Docker image for use by the bot's computer/tool subsystem:

- `ffmpeg`, `imagemagick`, `graphviz` (media processing)
- `pandoc` (document conversion)
- `sqlite3` CLI
- `fonts-noto-cjk`, `fonts-noto-color-emoji` (CJK + emoji rendering)
- Standard CLI: `git`, `curl`, `wget`, `jq`, `ripgrep`, `htop`, `tree`

## Package Management

- **Python**: `uv` (`pip install uv` then `uv pip install --system .`)
- **Frontend**: `npm` (via `package-lock.json`)
- **Lock file**: `uv.lock` (477 KB, checked in)

## Configuration Architecture

### Static Config (`config.yaml`)

- Loaded from `ACABOT_CONFIG` env var or default path
- Defines: gateway bind, agent defaults, runtime persistence, context compaction, plugin list, WebUI, filesystem layout
- Template: `config.example.yaml`

### Environment Variables (`.env`)

- `OPENAI_API_KEY` (and any provider-specific keys, consumed by litellm)
- `OPENAI_API_BASE` (optional override)
- Template: `.env.example`

### Filesystem-backed Runtime Config (`runtime_config/`)

The model registry and session/prompt configuration are entirely filesystem-driven:

| Directory | Content |
|---|---|
| `runtime_config/models/providers/` | Provider YAML files (API keys, base URLs) |
| `runtime_config/models/presets/` | Model preset YAML (temperature, max_tokens, etc.) |
| `runtime_config/models/bindings/` | Model binding YAML (maps task targets to provider+preset) |
| `runtime_config/prompts/` | System prompt Markdown files |
| `runtime_config/sessions/` | Session configuration YAML |
| `runtime_config/plugins/` | Plugin-specific config |

Template: `runtime_config.example/`

## Project Structure

```
AcaBot/
  src/acabot/                    # Python package root
    main.py                      # Entrypoint: asyncio bootstrap
    config.py                    # YAML config loader
    context.py                   # Request context
    gateway/                     # Messaging gateway layer
      napcat.py                  #   NapCat (OneBot v11 reverse WS)
      onebot_message.py          #   OneBot message segment parsing
      base.py                    #   Abstract gateway protocol
    agent/                       # LLM agent abstraction
      agent.py                   #   LitellmAgent (litellm.acompletion)
      tool.py                    #   Tool spec, executor, result types
      response.py                #   AgentResponse dataclass
      base.py                    #   BaseAgent ABC
    runtime/                     # Core runtime engine
      app.py                     #   RuntimeApp lifecycle
      pipeline.py                #   Message processing pipeline
      router.py                  #   Session routing
      agent_runtime.py           #   Agent execution orchestrator
      outbox.py                  #   Outbound message queue
      plugin_manager.py          #   Plugin loading & lifecycle
      gateway_protocol.py        #   Gateway protocol bridge
      approval_resumer.py        #   Tool-approval resume flow
      bootstrap/                 #   Component assembly & config loading
      backend/                   #   Session-agent bridge, persona, PI adapter
      builtin_tools/             #   computer, skills, sticky_notes, subagents
      computer/                  #   File I/O & shell execution backends
        backends.py              #     Host / Docker / Remote backends
        runtime.py               #     ComputerRuntime orchestrator
        workspace.py             #     Workspace path resolution
        media.py                 #     Media file handling
      context_assembly/          #   Prompt assembly & context window management
      contracts/                 #   Shared dataclasses & protocols
      control/                   #   HTTP control plane & WebUI API
        http_api.py              #     stdlib ThreadingHTTPServer REST API
        control_plane.py         #     Unified control-plane facade
        model_ops.py             #     Model CRUD operations
        session_loader.py        #     Session config filesystem ops
        reference_ops.py         #     Reference document operations
        snapshots.py             #     Runtime snapshot export
      inbound/                   #   Message preparation & image context
      memory/                    #   Conversation memory subsystem
        context_compactor.py     #     Summarization-based context compaction
        sticky_notes.py          #     Per-session sticky notes
        long_term_memory/        #     LanceDB-backed long-term memory
          storage.py             #       LanceDB read/write
          model_clients.py       #       LTM extractor, embedding, query planner
          extractor.py           #       Fact extraction from conversation
          ranking.py             #       Multi-signal retrieval ranking
      model/                     #   Model registry & resolution
        model_registry.py        #     Filesystem-backed provider/preset/binding
        model_resolution.py      #     Runtime model target resolution
        model_embedding_runtime.py # litellm.aembedding wrapper
        model_targets.py         #     System model target catalog
      plugins/                   #   Built-in runtime plugins
        ops_control.py           #     Slash-command ops plugin
        napcat_tools.py          #     QQ platform query tools
        reference_tools.py       #     Knowledge base search tools
        backend_bridge_tool.py   #     Backend bridge tool
      references/                #   Reference / knowledge-base subsystem
        local.py                 #     Local filesystem provider
        openviking.py            #     OpenViking RAG backend
      skills/                    #   Dynamic skill loading
      soul/                      #   System prompt assembly
      storage/                   #   Persistence layer
        sqlite_stores.py         #     SQLite: messages, threads, runs, events
        memory_store.py          #     In-memory fallback stores
      subagents/                 #   Sub-agent orchestration
      tool_broker/               #   Tool policy & execution broker
    types/                       #   Canonical event & action types
    webui/                       #   Pre-built Vue frontend assets
  extensions/                    # User-space extensions
    plugins/                     #   Extension plugins
    skills/                      #   Extension skills
    subagents/                   #   Extension sub-agents
  webui/                         # Vue 3 frontend source
  runtime_config.example/        # Example filesystem config
  deploy/                        # Docker Compose deployment
    compose.yaml                 #   Production: acabot + napcat
    compose.dev.yaml             #   Development overrides
  tests/                         # pytest + pytest-asyncio tests
```

## Container Architecture

### Dockerfile (full image)

- Base: `python:3.11-slim`
- Includes: build tools, media tools, Node.js, Playwright+Chromium, data science libs
- Exposes: `8080` (gateway WS), `8765` (WebUI HTTP)
- `PYTHONPATH=/app/src:/app/extensions`
- Used for production with Docker Compose

### Dockerfile.lite (minimal image)

- Base: `python:3.11-slim`
- Minimal tools: `git`, `curl`, `jq`, fonts
- Still includes Playwright+Chromium
- Same ports and entrypoint

### Docker Compose (`deploy/compose.yaml`)

Two-service stack:
- `acabot` (the bot) -- built from Dockerfile
- `napcat` (`mlikiowa/napcat-docker:latest`) -- QQ protocol bridge
- Shared `acabot_network` bridge network
- Volume mounts: `config.yaml`, `.env`, `runtime_config/`, `runtime_data/`, `extensions/`

## Extensions System

- Directory: `extensions/` (mounted into container at `/app/extensions`)
- Added to `PYTHONPATH` alongside `src/`
- Subdirectories: `plugins/`, `skills/`, `subagents/`
- Plugin loading via dotted-path strings in config (e.g., `acabot.runtime.plugins.ops_control:OpsControlPlugin`)

## Compute Backends (`src/acabot/runtime/computer/backends.py`)

| Backend | Status | Description |
|---|---|---|
| `HostComputerBackend` | Implemented | Direct shell execution on host |
| `DockerSandboxBackend` | Implemented | Per-thread Docker containers (`acabot-{hash}`) |
| `RemoteComputerBackend` | Stub | Placeholder, raises `NotImplemented` |

## Type Checking & Testing

- **Pyright** configured in `pyproject.toml` (`pythonVersion = "3.11"`, `extraPaths = ["src"]`)
- **pytest** with `asyncio_mode = "auto"`, test directory: `tests/`
