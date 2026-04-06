# Admin Host Runs, Skill Refresh, and Group Session Computer Cases Design

**Date:** 2026-04-06
**Status:** Approved for implementation

## Goal

Make group frontstage runs split cleanly by sender role:

- normal members run in sandbox (`docker` backend)
- group admins / owners run in host mode

On top of that, let an admin-triggered host frontstage run install skills by itself using `bash` (download + unpack into the skill catalog directory), then explicitly refresh the extension catalog so the new skills become available to later runs.

This round does **not** try to make a newly installed skill available inside the same run. Later runs being able to see it is sufficient.

## Non-Goals

- No dedicated `install_skill` builtin tool
- No attempt to make `/skills` become the writable skill source of truth
- No requirement that the current run immediately gains the newly installed skill
- No foreground-worker-specific handling in this round
- No broad `reload-config` tool exposure to the model

## Decisions

### 1. Skill installation stays as host-side file operations

Admin frontstage runs in host mode already have the right execution shape for installation:

- the model uses `bash`
- downloads archives from the network
- unpacks them into the configured skill catalog directory
- ensures the package has a valid `SKILL.md`

There is no separate install surface. Installation is just file placement into the real catalog root.

### 2. Add a narrow extension refresh surface

Introduce a narrow refresh contract instead of exposing full runtime reload.

Model-facing builtin tool:

```text
refresh_extensions(kind="skills")
```

Control-plane-facing operation:

- refresh only extension catalogs relevant to the requested `kind`
- initial supported kind: `skills`
- design the API so more kinds can be added later (`subagents`, `all`, etc.)

This keeps the model-facing action aligned with the real use case: “I just changed extensions on disk; refresh what the bot can see.”

### 3. Tool visibility must stay stable

Do **not** add special run-time visibility gating for `refresh_extensions` based on host/admin state.

Reason:

- changing per-run tool inventory affects tool description stability
- that in turn affects prompt caching characteristics

So the tool surface stays statically controlled by the normal agent tool allowlist. Whether a specific call succeeds is enforced by the tool implementation and runtime context, not by dynamically hiding the tool.

### 4. Refresh must solve both catalog discovery and frontstage allowlists

Refreshing only `SkillCatalog.reload()` is not enough.

Current skill usage is gated by:

1. skill catalog discovery
2. session-owned agent `visible_skills`
3. run-time world visibility

Therefore `refresh_extensions(kind="skills")` must do two things:

1. reload the skill catalog from disk
2. realign the current session-owned frontstage agent's `visible_skills` with the refreshed skill catalog

Target behavior:

- admin host run installs a skill under the configured catalog root
- admin calls `refresh_extensions(kind="skills")`
- runtime reloads the catalog
- runtime updates the current session's `agent.yaml.visible_skills`
- later runs in that same session can see and use the new skill

### 5. Group session computer policy becomes sender-role-aware by default

For QQ group sessions, the default execution policy must become:

- `owner` / `admin` → host backend
- other members → docker backend

This belongs in session `computer.cases`, not in ad-hoc code branches.

The split must be applied in two places:

1. existing checked-in group session configs
2. the default session payload produced for new `qq_group` sessions

## Architecture

## A. Session config layer

Use surface-level `computer` domain cases keyed by `sender_roles`.

For responding group surfaces (`message.mention`, `message.reply_to_bot`, and any other group message surface that should execute tools), define:

- default case for ordinary members: sandbox / docker
- explicit case for `sender_roles: [owner, admin]`: host

The computer payload should control:

- `backend`
- `allow_exec`
- `allow_sessions`
- roots visibility as needed by the current work-world model

The design keeps the distinction declarative and inspectable through session config.

## B. Extension refresh service layer

Add a dedicated runtime/control-plane service path for extension refresh.

Responsibilities for `kind="skills"`:

1. reload the skill catalog loader
2. rebuild the catalog contents
3. resolve the current session-owned frontstage agent
4. overwrite that session agent's `visible_skills` with the refreshed skill names
5. refresh dependent session bundle / agent loader state so later runs use the new allowlist

The operation returns a structured summary, for example:

- refreshed kind
- discovered skill names
- updated session id / agent id
- whether files were changed
- note that later runs will see the result

## C. Builtin tool layer

Add a new builtin tool:

```text
refresh_extensions(kind: string)
```

Initial contract:

- accepted values: `skills`
- execution delegates to the new extension refresh service
- failure is explicit if runtime context is insufficient (for example no active session-owned frontstage agent)

This tool is intentionally narrow:

- no generic config reload semantics
- no plugin reload semantics in the first round
- no hidden side path to unrelated runtime state changes

## D. HTTP / control plane layer

Add a matching narrow control-plane operation and HTTP endpoint, e.g.:

- control plane: `refresh_extensions(payload)`
- HTTP: `POST /api/runtime/refresh-extensions`

Builtin tool and HTTP endpoint must share the same underlying refresh implementation so there is only one behavior definition.

## Data Flow

### Admin installs a skill

1. admin message hits a group frontstage surface
2. session `computer.cases` resolves this run to host backend
3. model uses `bash` to download and unpack a skill into the configured skill catalog root
4. model calls `refresh_extensions(kind="skills")`
5. refresh service reloads catalog and rewrites current session agent `visible_skills`
6. current run completes
7. next run in the same session sees the new skill in normal skill discovery and prompt summaries

### Ordinary member message

1. member message hits the same group surface
2. session `computer.cases` resolves to docker backend
3. run stays sandboxed
4. no host-side installation path is available

## Configuration Strategy

### Existing group sessions

Update checked-in `runtime_config/sessions/qq/group/*/session.yaml` files so they stop relying purely on static agent computer policy.

The intent is that role-based execution policy is visible directly in `session.yaml`.

### New `qq_group` sessions

When control plane creates a new `qq_group` session bundle, the generated `session.yaml` must include the same role-based `computer` defaults.

This prevents newly created group sessions from silently missing the admin/member split.

## Testing Strategy

### Config and session-runtime tests

- session loader / runtime tests proving `sender_roles=[owner]` and `sender_roles=[admin]` resolve to host backend
- tests proving ordinary members resolve to docker backend
- tests for default group session payload creation including the new `computer.cases`

### Refresh service tests

- create a temporary skill under the configured skill root
- run `refresh_extensions(kind="skills")`
- assert catalog reload sees the new skill
- assert current session agent `visible_skills` is rewritten to include it
- assert later session bundle loads validate successfully against the refreshed catalog

### Builtin tool tests

- tool delegates to refresh service
- `kind="skills"` returns a stable success payload
- unsupported kinds fail clearly

### Integration shape tests

- simulate an admin host run that installs a skill on disk, refreshes extensions, then verify a later run exposes that skill through normal skill visibility

## Risks and Constraints

- Rewriting `visible_skills` means refresh is session-scoped behavior, not purely global catalog behavior. This is intentional because the current product model uses session-owned agents as the frontstage allowlist boundary.
- Because the tool inventory should stay stable for prompt caching, authorization should not rely on dynamically hiding `refresh_extensions` per run.
- Same-run availability is explicitly deferred. If foreground-worker semantics later require in-run extension visibility updates, that should be handled as a separate design.

## Deferred

- `refresh_extensions(kind="subagents")`
- `refresh_extensions(kind="all")`
- plugin extension refresh
- current-run immediate skill visibility after refresh
- foreground worker special handling
