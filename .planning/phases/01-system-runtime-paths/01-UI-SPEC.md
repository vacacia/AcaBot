---
phase: 01
slug: system-runtime-paths
status: approved
shadcn_initialized: false
preset: none
created: 2026-03-29
---

# Phase 01 — UI Design Contract

> Visual and interaction contract for frontend phases. Generated in local fallback mode for `gsd-ui-phase`, then self-verified against the current AcaBot design system and Phase 1 context.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | none |
| Icon library | inline icon / text-first controls |
| Font | `Inter`, `Noto Sans SC`, `PingFang SC`, `Microsoft YaHei`, `sans-serif` |

### Contract Notes

- This phase **must extend the current AcaBot glass-console language** rather than introducing a new dashboard style.
- `webui/src/styles/design-system.css`, `webui/src/App.vue`, and `webui/src/components/AppSidebar.vue` remain the visual source of truth.
- System page UI should feel like a first-party control surface inside the existing shell, not a special-case admin utility panel.

---

## Layout Contract

### Page Hierarchy

1. **Hero / page intro**
   - Eyebrow: `System`
   - Title speaks in product language, not internal implementation jargon
   - Summary explains that this page manages shared system-level configuration

2. **System configuration body**
   - Shared gateway settings
   - Catalog scan path management
   - Shared admin list
   - Maintenance actions

3. **Advanced section**
   - Collapsible by default
   - Read-only “path and source-of-truth overview”
   - Explains actual config path, resolved base dir, resolved catalog roots, and major runtime data locations

### Block Order

| Order | Block | Reason |
|------|-------|--------|
| 1 | Gateway config | Most obvious shared entrypoint |
| 2 | Catalog scan roots | Directly affects later skill/subagent pages |
| 3 | Shared admins | Important but lower-frequency edit |
| 4 | Maintenance actions | Operational, should stay isolated |
| 5 | Advanced diagnostics | Useful for confidence and debugging, but not mainline editing |

### Width and Grid

- Default content uses the existing `ds-page` and `ds-panel` layout.
- Main editable areas use 2-column form grids on desktop when fields are naturally paired.
- List editors and advanced diagnostics collapse to single column on narrower screens.
- Advanced diagnostics may use 2 or 3 summary cards, but must keep labels human-readable.

---

## Spacing Scale

Declared values (must be multiples of 4):

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Inline icon gaps, tag edge breathing room |
| sm | 8px | Field helper spacing, item chips, inline warning gaps |
| md | 16px | Default card internals, field-to-field spacing |
| lg | 24px | Hero and section padding rhythm |
| xl | 32px | Major group separation inside the page |
| 2xl | 48px | Separation between hero and major body sections |
| 3xl | 64px | Reserved for future full-page breaks only |

Exceptions: panel border radius may continue using the existing `28px / 30px` shell language; buttons may continue using the existing `16px` radius language.

### Practical Rules

- No configuration block should visually collapse into the next one; each block must have a clear panel boundary.
- Within a list editor, entry input and action buttons should feel compact and fast, using `sm` and `md` rhythm rather than oversized dashboard spacing.
- Advanced diagnostics should read denser than the main form, but not like raw debug output.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px–15px | 400–500 | 1.6 |
| Label | 13px | 700 | 1.35 |
| Heading | 24px–32px | 700–800 | 1.15 |
| Display | 30px–46px | 800 | 1.08 |

### Typography Contract

- Titles and section headings stay crisp and slightly editorial, matching the current shell.
- Form labels must use product terms such as `配置文件位置`, `扫描目录预览`, `共享管理员`, not raw config keys.
- Helper text should explain effect and lifecycle, for example:
  - whether save attempts hot-apply
  - whether a setting requires restart
  - what a resolved path preview means

### Forbidden Copy Style

- No direct exposure of raw internal field names as primary labels, such as `skill_catalog_dirs` or `base_dir`.
- No unexplained infrastructure jargon in mainline copy.
- No “developer-only” sarcasm or placeholder text.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#f7f1ef` light / `#0e1218` dark | Page background, shell atmosphere |
| Secondary (30%) | `rgba(255,255,255,0.18)` light / `rgba(25,31,44,0.16)` dark | Panels, cards, elevated surfaces |
| Accent (10%) | `#ff6479` default via `var(--accent)` | Eyebrows, primary CTA, active emphasis, selected list affordances |
| Destructive | `#ef4f62` | Remove item, destructive confirmation, hard errors only |

Accent reserved for: hero eyebrow, primary save/apply controls, selected interactive emphasis, compact diagnostic highlights, and active list-editor feedback. Never use accent on every border, every label, or every neutral button.

### State Colors

- Success uses existing `var(--success)` for `已保存并已生效`.
- Warning uses existing `var(--warning)` for `已保存，但需重启` and `已写入，但应用失败`.
- Error uses existing `var(--danger)` for hard failure states.
- Informational diagnostics may use existing `var(--info)` sparingly in the advanced section.

---

## Component Contract

### Gateway Config

- Presented as a calm form panel, not as a raw transport/debug block.
- `host`, `port`, `token`, `timeout` follow the existing field style.
- Restart-sensitive fields must show a short helper note before save, not only after failure.

### Catalog Path Editor

- Uses a **single-item list editor** pattern instead of multiline textarea.
- One input row for “add item”, one confirmation action, optional batch import as secondary action.
- Existing items render as removable rows/chips with clear delete affordance.
- Below the editable list, show a read-only resolved directory preview.

### Shared Admin List

- Same single-item list editor pattern as catalog paths.
- Each admin entry should feel like an identity item, not an arbitrary string blob.

### Maintenance Actions

- Maintenance controls live in a separate low-emphasis panel.
- “重新读取配置” is secondary, never visually stronger than save actions.
- Maintenance actions need short explanation text clarifying when they are actually needed.

### Advanced Diagnostics

- Hidden behind an explicit “高级信息 / 路径总览” disclosure.
- Uses summary rows/cards with two layers:
  - human-readable label
  - actual resolved path/value in mono or compact technical style
- Technical detail is welcome here, but each item must still answer a human question:
  - which file is in use
  - which root is being scanned
  - where runtime data lands

---

## Interaction Contract

### Save Semantics

- Default CTA language is “保存并尝试生效” or equivalent.
- After save, result feedback must distinguish:
  - saved and applied
  - saved but restart required
  - save failed before write
  - written but apply/reload failed

### Validation

- Frontend validates only reliable local rules:
  - empty input
  - malformed numeric ranges
  - duplicate item in current list
  - immediate field-level conflicts
- Filesystem existence/readability checks remain backend-authoritative.
- If backend rejects a path, the UI must preserve the user’s draft and explain the failure.

### Error Presentation

- Top-level feedback is plain-language and actionable.
- Technical details live behind disclosure or expandable detail text.
- Error copy must help the user decide whether to:
  - correct an input
  - retry
  - restart runtime
  - inspect advanced diagnostics

### Advanced Section Behavior

- Closed by default after first load.
- State may remain open during the current session if the user explicitly expands it.
- Expansion should not visually hijack the whole page; it is a secondary information plane.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | 保存并尝试生效 |
| Empty state heading | 还没有配置任何条目 |
| Empty state body | 先添加一项，AcaBot 会在保存后解析实际生效位置，并在下方展示预览。 |
| Error state | 保存失败。请检查输入项，必要时展开技术详情查看具体原因。 |
| Destructive confirmation | 移除条目：确认后，这一项将不会再参与系统共享配置。 |

### Copy Rules

- Labels should describe purpose, not schema shape.
- Examples:
  - Good: `技能扫描目录`
  - Good: `当前实际扫描到的目录`
  - Avoid as primary label: `skill_catalog_dirs`, `resolved_skill_catalog_dirs`
- Helper text should always answer “这项改了会怎样”.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not required |
| third-party UI registry | none | shadcn view + diff required |

### Safety Rule

- This phase should reuse the existing AcaBot design system and local components.
- Do not introduce a new component registry, external admin theme, or one-off form toolkit just for the system page.

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-03-29
