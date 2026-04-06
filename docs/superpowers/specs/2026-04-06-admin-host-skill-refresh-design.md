# Bot Admin Host Runs and Skill Refresh Design

**Date:** 2026-04-06
**Status:** Draft for re-review

## Goal

Make QQ group frontstage runs split by **bot-config admin identity**, not by QQ group role:

- bot actual admins (from WebUI / config `admin_actor_ids`) run in `host`
- everyone else runs in sandbox / `docker`

On top of that, let an admin-triggered host frontstage run install skills by itself using `bash` into the real skill catalog root, then explicitly refresh extensions so the new skills become available to **later runs**.

## Non-Goals

- No dedicated `install_skill` builtin tool
- No attempt to make `/skills` become writable source of truth
- No requirement that the current run immediately gains the newly installed skill
- No dynamic tool visibility gating for `refresh_extensions`
- No QQ owner/admin/member based host routing in this round
- No extra host-lock design in this round

## Key Decisions

### 1. Admin identity comes from bot config, not QQ group role

This change must follow the same product meaning as AstrBot:

- admin means the bot operator configured in WebUI / config
- admin does **not** mean QQ 群主 / 群管理员
- a normal group member may still be bot admin
- a QQ group owner/admin may still be non-admin for AcaBot

The existing shared admin source of truth is `admin_actor_ids`.

This round should reuse that same source for:

- frontstage host/sandbox session decisions
- builtin tool authorization
- control-plane refresh authorization

There must not be a second, unrelated “session admin” list.

### 2. Add explicit `is_bot_admin` facts instead of overloading `sender_roles`

Current session matching only knows about:

- `actor_id`
- `sender_roles`

`sender_roles` currently means platform/group role and is the wrong axis for this feature.

For this round, add a dedicated admin fact to the session matcher layer:

- `EventFacts.is_bot_admin: bool`
- `MatchSpec.is_bot_admin: bool | None`

`SessionRuntime.build_facts()` should set `is_bot_admin=True` when the current `actor_id` is in the configured shared admin set.

This is preferred over:

- pretending bot admin is a sender role
- generating explicit `actor_id` cases into every group session
- baking admin logic into ad-hoc computer runtime branches

Reason: the policy stays declarative in `session.yaml`, while still following the global admin config.

### 3. `/skills` stays a read-only run-time view for everyone

`/skills` keeps one stable meaning:

- the current run's mirrored skill view
- readable/usable by the run
- not the writable installation target

This must stay true for both:

- ordinary sandbox runs
- admin host runs

Do **not** make `/skills` switch semantics based on who is speaking.

Admin host runs differ only in that they additionally gain maintenance access to:

- the real resolved skill catalog root on host
- the target session `agent.yaml` rewritten on refresh
- the builtin refresh action

### 4. Skill installation remains host-side file operations

Admin host runs install skills by:

- using `bash`
- downloading/unpacking into the real catalog root
- ensuring a valid `SKILL.md`
- calling `refresh_extensions(kind="skills")`

The writable install target is the real catalog root on disk, not `/skills`.

Resolver rule:

- reuse the same catalog dir resolver as runtime skill discovery
- collect resolved roots with `scope == "project"`
- require exactly one project-scope root
- fail clearly if zero or multiple project roots exist

`extensions/skills` is only the default when config does not override it.

### 5. Restriction model: environment boundary + execution-time auth

Do **not** restrict this by dynamically hiding `/skills` or dynamically hiding the tool.

Instead:

- non-admin messages resolve to sandbox / docker
- sandbox runs do not get direct access to the real host skill source of truth
- admin messages resolve to host
- only admin host runs can touch the real catalog root
- `refresh_extensions` stays statically visible through normal `visible_tools`, but execution validates permissions

Tool auth rule for this round:

- caller must be the session-owned frontstage agent
- current facts must say `is_bot_admin=True`
- effective computer backend must be `host`

### 6. Group session computer policy becomes bot-admin-aware by default

For QQ group responding surfaces, default policy becomes:

- default: `docker`
- case when `is_bot_admin: true`: `host`

This applies to:

- `message.mention`
- `message.reply_to_bot`
- `message.plain`

Notice surfaces remain unchanged.

This must be applied in two places:

- existing checked-in QQ group sessions
- newly created `qq_group` session bundles

### 7. Refresh rewrites session skill allowlist for later runs

`refresh_extensions(kind="skills")` must:

1. reload the skill catalog
2. compute the effective winner set by skill name
3. rewrite the current session-owned frontstage agent `visible_skills`
4. refresh/invalidate bundle-loader state so later runs load the new list

For this round, refresh is intentionally a **session capability mutation**, not just cache refresh.

## Architecture

## A. Shared admin source of truth

Reuse the existing shared admin configuration path already exposed in system settings:

- config / WebUI: `admin_actor_ids`
- bootstrap/runtime app backend entry already consumes it

This round extends that same config to the session decision path.

Implementation shape:

- `SessionRuntime` must know the current shared admin actor set
- config reload / admin update must refresh that set for later runs

## B. Session facts and matcher contract

Extend session-config contracts:

- `EventFacts.is_bot_admin: bool = False`
- `MatchSpec.is_bot_admin: bool | None = None`

Matcher semantics:

- if `MatchSpec.is_bot_admin is not None`, require exact equality with facts

`SessionRuntime.build_facts()` computes:

- `actor_id = "{platform}:user:{user_id}"`
- `is_bot_admin = actor_id in shared_admin_actor_ids`

This keeps session rules declarative and inspectable.

## C. Session config layer

For QQ group responding surfaces, use `computer.default + cases` keyed by `is_bot_admin`.

Target shape:

```yaml
surfaces:
  message.mention:
    computer:
      default:
        backend: docker
        allow_exec: true
        allow_sessions: true
      cases:
        - case_id: bot_admin_host
          when:
            is_bot_admin: true
          use:
            backend: host
            allow_exec: true
            allow_sessions: true
```

Same shape applies to:

- `message.reply_to_bot`
- `message.plain`

World/root policy:

- all normal frontstage runs keep `/workspace`, `/skills`, `/self`
- non-admin sandbox runs still only reach sandboxed world roots
- admin host runs may also perform explicit host maintenance against the resolved real skill root and target session config path

That maintenance access should be described via run-scoped guidance / reminders, not by changing `/skills` semantics.

## D. Admin-host maintenance guidance

When the current run is:

- frontstage
- `is_bot_admin=True`
- `backend=host`

inject extra model-readable maintenance guidance that surfaces:

- the resolved writable project skill root
- the target session-owned `agent.yaml` path that refresh will rewrite
- the reminder that `/skills` is only a mirrored view, not the install target

This carve-out is run-scoped and should not weaken the default `/workspace` guidance for ordinary runs.

## E. Builtin tool layer

Add:

```text
refresh_extensions(kind: string)
```

Initial supported kind:

- `skills`

Rules:

- tool remains controlled by ordinary `visible_tools`
- no dynamic visibility gating based on admin/host state
- execution-time auth enforces `frontstage agent + is_bot_admin + host`

Checked-in QQ group frontstage agents and new `qq_group` defaults must include `refresh_extensions` in `visible_tools`.

## F. Refresh service layer

For `kind="skills"`, the shared refresh implementation must:

1. resolve/reload skill catalog roots using the same runtime resolver semantics
2. reload catalog contents
3. resolve the target session-owned frontstage agent
4. rewrite `agent.yaml.visible_skills` to the full discovered winner set
5. refresh session bundle loader catalog snapshots
6. invalidate cached bundles so later runs re-read the rewritten file

The operation returns a structured summary including:

- refreshed kind
- resolved project install target, when unique
- resolved roots reloaded
- discovered skill names
- target session id / agent id
- whether `agent.yaml` changed
- note that later runs will see the result

## G. HTTP / control plane layer

Add a narrow control-plane operation and endpoint, e.g.:

- control plane: `refresh_extensions(payload)`
- HTTP: `POST /api/runtime/refresh-extensions`

Wrapper auth:

- builtin tool wrapper: `frontstage agent + is_bot_admin + host`
- HTTP wrapper: loopback-only, explicit `session_id`

Both wrappers call the same refresh core.

## Configuration Strategy

### Existing checked-in QQ group sessions

Update `runtime_config/sessions/qq/group/*/session.yaml` so responding surfaces stop relying on platform sender roles for host routing.

They should use:

- default docker
- `is_bot_admin: true` case -> host

### New `qq_group` sessions

When `create_session()` generates a new `qq_group` bundle and caller did not supply explicit surfaces:

- seed the same default responding surfaces
- seed the same `computer` cases with `is_bot_admin: true`
- seed the normal frontstage tool baseline plus `refresh_extensions`

Do not leave newly created group sessions on static host default.

## Data Flow

### Bot admin installs a skill

1. admin speaks in QQ group
2. session facts mark `is_bot_admin=True`
3. responding surface computer case resolves to `host`
4. model uses `bash` against the resolved real skill root
5. model calls `refresh_extensions(kind="skills")`
6. refresh rewrites current session `agent.yaml.visible_skills`
7. later runs in that session can use the new skill through normal `/skills` visibility

### Ordinary group member

1. member speaks in same QQ group
2. session facts mark `is_bot_admin=False`
3. responding surface falls through to default `docker`
4. run stays sandboxed
5. run may read `/skills`, but cannot modify real host skill roots or successfully call refresh

## Testing Strategy

### Facts / matcher tests

- `SessionRuntime.build_facts()` marks configured admin actor as `is_bot_admin=True`
- non-admin actor gets `False`
- `MatchSpec(is_bot_admin=True)` matches only admin facts

### Session-runtime tests

- QQ group responding surfaces resolve to `host` when `is_bot_admin=True`
- same surfaces resolve to `docker` when `is_bot_admin=False`
- no dependence on QQ `sender_role`

### Session creation tests

- new `qq_group` session defaults include the bot-admin-aware `computer` cases
- new `qq_group` frontstage tool list includes `refresh_extensions`

### Refresh service tests

- temp skill added under resolved project skill root
- refresh reloads catalog
- target session `visible_skills` rewritten to include new winner set
- stale removed skills are dropped
- later bundle loads validate successfully

### Builtin tool auth tests

- non-admin run calling refresh is rejected
- admin sandbox run calling refresh is rejected
- admin host run calling refresh succeeds

## Risks and Constraints

- This design assumes host maintenance is effectively a single-operator path for now. If multi-admin or concurrent host maintenance becomes real later, add explicit host serialization/locking.
- Refresh is intentionally session-scoped because current product capability boundaries live on session-owned agents.
- Same-run immediate skill visibility is still deferred.

## Deferred

- `refresh_extensions(kind="subagents")`
- `refresh_extensions(kind="all")`
- same-run skill visibility after refresh
- explicit host locking / queueing
- broader admin-maintenance UX improvements
