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

Important boundary: the writable install target is **not** `/skills`. `/skills` remains the per-run mirrored skill view. The install target is the real catalog root on disk (normally project `extensions/skills`).

Because the current frontstage workspace reminder says work should stay in `/workspace`, this round must also add an explicit admin-host carve-out in prompt/tool guidance: when an admin host run is performing extension maintenance, it may operate on the real extension catalog root and session config files outside `/workspace`. That guidance must name the project skill source of truth clearly enough that the model does not confuse it with `/skills`.

This carve-out must be **run-scoped**, not a global weakening of the normal `/workspace` reminder. In practice that means adding an extra reminder/tool-guidance contribution only for `owner|admin + host` runs.

That run-scoped guidance must surface, in model-readable form:

- the resolved writable project skill root for the current installation attempt
- the target session-owned agent config path that will be rewritten on refresh

Without that, the model still cannot reliably distinguish the real host paths from `/skills` and `/workspace`.

The model must not blindly assume `extensions/skills`. Before installation it should resolve the effective skill catalog roots from runtime configuration (`runtime.filesystem.skill_catalog_dirs`).

Resolver rule for this round: install-target selection, model-visible resolved paths, and live catalog reload must all use the **same shared resolver/source of truth** as the runtime skill catalog itself. Do not invent a separate control-plane-only path interpretation for installation. In implementation terms, this should reuse the runtime catalog directory resolver (`resolve_skill_catalog_dirs()` or an extracted shared helper with identical semantics), not a separately interpreted control-plane path view.

Install-target selection rule for this round:

- collect the resolved catalog roots whose scope is `project`
- if there is exactly one project-scope root, use it as the writable install target
- if there are zero project-scope roots, fail clearly instead of installing into a user-scope root
- if there are multiple project-scope roots, fail clearly; multi-project-root install precedence is out of scope for this round

`extensions/skills` is only the default fallback when no explicit override is configured.

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

### 3. Avoid adding extra dynamic tool gating

Do **not** add special run-time visibility gating for `refresh_extensions` based on host/admin state.

Reason:

- the runtime already has some dynamic tool metadata churn (`Skill`, subagents, etc.)
- this round should not introduce one more run-specific gate for the new refresh tool
- that keeps the new tool aligned with the normal agent tool allowlist and avoids extra prompt-caching instability beyond what already exists

So the tool surface stays statically controlled by the normal agent tool allowlist. Whether a specific call succeeds is enforced by the tool implementation and runtime context, not by dynamically hiding the tool.

Authorization rule for this round:

- `refresh_extensions` must reject unless the caller is the session-owned frontstage agent
- the current run must be an `owner` or `admin` run
- the effective computer backend for the run must be `host`

This keeps the tool statically present while still enforcing the admin-host maintenance boundary at execution time.

### 4. Refresh must solve both catalog discovery and frontstage allowlists

Refreshing only `SkillCatalog.reload()` is not enough.

Current skill usage is gated by:

1. skill catalog discovery
2. session-owned agent `visible_skills`
3. run-time world visibility

Therefore `refresh_extensions(kind="skills")` must do two things:

1. reload the skill catalog from disk
2. realign the current session-owned frontstage agent's `visible_skills` with the refreshed skill catalog

For this round, “realign” means **rewrite `visible_skills` to the exact currently discovered skill name set for the target session-owned frontstage agent**, not append-only mutation. That keeps disk state consistent in both directions:

- newly installed skills are added
- removed skills are dropped
- later session bundle validation does not fail on stale references

This is an intentional **session capability change** for the target frontstage agent, not a neutral cache refresh. In practical terms, after a successful refresh, that session's frontstage agent adopts the full currently discovered skill set from the configured skill catalog roots.

The rewritten list must be persisted as a stable, deduplicated, name-only list derived from the catalog's **effective winner set by skill name**, not from raw manifest rows. Existing catalog precedence rules decide the winner for each skill name before `visible_skills` is rewritten.

Target behavior:

- admin host run installs a skill under the configured catalog root
- admin calls `refresh_extensions(kind="skills")`
- runtime reloads the catalog
- runtime updates the current session's `agent.yaml.visible_skills`
- later runs in that same session can see and use the new skill

### 5. Group session computer policy becomes sender-role-aware by default

For QQ group sessions, the default execution policy must become:

- `owner` → host backend
- `admin` → host backend
- `member` → docker backend

`sender_roles` matching here relies on the existing event model, where a run carries **one canonical sender role** (`owner` / `admin` / `member`) and `EventFacts.sender_roles` is a one-item list used only for matcher compatibility. The matcher implementation uses set intersection, but under the current event model that still means one effective role per run. If upstream facts ever become multi-role in the future, this design must be revisited with an explicit composite/preferred-role rule instead of assuming the separate `owner` and `admin` cases remain safe.

This belongs in session `computer.cases`, not in ad-hoc code branches.

The split must be applied in two places:

1. existing checked-in group session configs
2. the default session payload produced for new `qq_group` sessions

## Architecture

## A. Session config layer

Use surface-level `computer` domain cases keyed by `sender_roles`.

For responding group surfaces, define explicit computer cases on the concrete keys already used by QQ group sessions:

- `message.mention`
- `message.reply_to_bot`
- `message.plain`

Initial implementation should cover the responding message surfaces above. Non-responding notice surfaces remain unchanged.

This round intentionally does **not** introduce a new `message.command` surface into existing group sessions. Today slash-command-like traffic can continue to fall through the existing surface chain and land on `message.plain` unless a future change explicitly adds `message.command` together with mirrored admission/routing/computer semantics.

For each of those responding surfaces:

- default case for ordinary members: sandbox / docker
- explicit case for `sender_roles: [owner]`: host
- explicit case for `sender_roles: [admin]`: host

The computer payload must control:

- `backend`
- `allow_exec`
- `allow_sessions`
- roots visibility

This root policy is part of the sandbox boundary, not an optional detail. In particular:

- member / docker runs must keep the normal frontstage world roots only (`/workspace`, `/skills`, `/self`) and must **not** gain direct world-path access to the real catalog root or session config source of truth
- admin / host runs may keep the normal frontstage roots and also rely on the admin-host maintenance carve-out for host-path operations against the real extension catalog root and session config files

The design keeps the distinction declarative and inspectable through session config.

## B. Extension refresh service layer

Add a dedicated runtime/control-plane service path for extension refresh.

Responsibilities for `kind="skills"`:

1. reload the skill catalog loader
2. rebuild the catalog contents
3. resolve the current session-owned frontstage agent
4. overwrite that session agent's `visible_skills` with the refreshed skill names
5. refresh dependent session bundle / agent loader state so later runs use the new allowlist

Step 5 must explicitly cover both pieces of loader state:

- refresh the session bundle loader's catalog-name snapshot used for `visible_skills` validation
- invalidate any cached session bundles so the rewritten `agent.yaml` is re-read immediately instead of waiting for cache expiry

The operation returns a structured summary, for example:

- refreshed kind
- resolved project install target (when uniquely determined)
- resolved catalog roots reloaded
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

The tool remains statically controlled by the agent tool allowlist. For this round, checked-in QQ group session-owned agents and new `qq_group` session defaults must include `refresh_extensions` in `visible_tools` so the builtin tool can actually appear without introducing extra dynamic gating logic.

That requirement applies to the agent creation path as well: when a new `qq_group` session bundle is created, the generated `agent.yaml` default must seed the normal qq_group frontstage tool baseline and then append `refresh_extensions`, rather than starting from an otherwise empty tool list.

Because session bundle validation rejects unknown tool names, builtin registration for `refresh_extensions` must happen before session bundle validation snapshots are built or refreshed.

## D. HTTP / control plane layer

Add a matching narrow control-plane operation and HTTP endpoint, e.g.:

- control plane: `refresh_extensions(payload)`
- HTTP: `POST /api/runtime/refresh-extensions`

Builtin tool and HTTP endpoint must share the same underlying refresh implementation so there is only one behavior definition.

Target selection rules:

- builtin tool path may derive the target session-owned frontstage agent from the current run context
- HTTP / control-plane path must accept an explicit target identifier, at minimum `session_id`, so the service knows which `agent.yaml` to rewrite

The shared implementation must refresh not only the catalog but also the session bundle loader's catalog snapshot before reloading the rewritten session bundle, so `visible_skills` validation uses the refreshed skill-name set.

HTTP auth rule for this round:

- the endpoint is privileged local-admin control-plane functionality, not a public conversation tool surface
- `POST /api/runtime/refresh-extensions` must be loopback-only in this round
- the HTTP wrapper authorizes loopback access and requires explicit `session_id`
- the builtin-tool wrapper authorizes `owner|admin + host + session-owned frontstage agent`
- after wrapper-level auth succeeds, both entrypoints call the same refresh core for the actual catalog reload + `visible_skills` rewrite
- this feature does not rely on broad `/api/runtime/reload-config`; any existing broader reload endpoint behavior is out of scope and must not be treated as the security model for extension refresh

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

Concretely, the session creation path must seed those `computer` blocks when:

- `template_id == "qq_group"`
- the caller did not already provide explicit `surfaces`

This prevents newly created group sessions from silently missing the admin/member split while still letting explicit caller-provided surfaces override the defaults.

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
