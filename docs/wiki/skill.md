# Skill 系统

## 扫描与解析

### 根目录

`FileSystemSkillPackageLoader` 在启动时和热重载时，从配置的扫描根目录递归查找所有 `SKILL.md`。

配置项：`runtime.filesystem.skill_catalog_dirs`，默认值：

```
./.agents/skills    → project scope
~/.agents/skills    → user scope
```

### Scope 推断

| 写法 | scope |
|------|-------|
| 相对路径（如 `./skills`） | `project` |
| `~` 路径或绝对路径 | `user` |

同名 skill 存在时 **project 优先于 user**。

### 命名

`skill_name` 由目录相对路径推导，嵌套用 `:` 分隔：

```
skills/
├── debugging/SKILL.md         → "debugging"
└── data/
    └── excel/SKILL.md         → "data:excel"
```

### 解析

`parse_skill_package()` 拆分 `SKILL.md` 的 YAML frontmatter 和正文。

frontmatter 字段映射：

```
SKILL.md frontmatter
  ├─ description               → manifest.description          （必填，缺了抛 SkillPackageFormatError）
  ├─ name                      → manifest.metadata["display_name"]
  ├─ argument-hint             → manifest.argument_hint
  ├─ disable-model-invocation  → manifest.disable_model_invocation
  └─ 其他字段                  → manifest.metadata             （透传，不丢失）
```

格式错误的 skill 会被跳过并记录 warning，不阻塞启动。

### 热重载

`ConfigControlPlane` 在配置热更新时调用 `SkillCatalog.reload()` 重新扫描全部根目录，新 skill 无需重启即可生效。

## 可见性

三层过滤，全部通过后 skill 才能到达模型：

1. **Catalog 层**：skill 必须在扫描目录中存在且格式正确
2. **Profile 层**：`profile.skills` 白名单过滤

```yaml
runtime:
  profiles:
    aca:
      skills:
        - data:excel
        - debugging
```

白名单中不存在的 skill 会被自动忽略。

3. **Run 层**：`WorldView.visible_skill_names` 决定本次 run 的实际权限

   - session-driven computer 决策提供了 `visible_skills` → 使用它
   - 否则回退到 `profile.skills`
   - `/skills` root 被隐藏或列表为空时，`Skill` 工具不会暴露给模型

## 模型加载 Skill 的链路

模型本身不直接访问文件系统，它通过一条三步链路来加载和使用 skill：先在 system prompt 中看到可用 skill 的摘要列表，再通过 `Skill` 工具按名称读取完整内容，最后通过 `/skills/` 路径访问 skill 包内的参考资料和脚本。

### 第一步：从 prompt 摘要中感知 skill

每一轮对话开始时，runtime 会把当前可见 skill 的名称和描述注入到 system prompt 中。模型拿到这段文本后，才能知道"现在有哪些 skill 可以用"。这段摘要只包含 `skill_name` 和 `description` 两个字段，不包含 SKILL.md 的正文内容。

注入格式如下：

```
<system-reminder>
The following skills are available for use with the Skill tool:

- data:excel: 处理 Excel 文件的标准工作流。
- debugging: 系统性调试任何 bug 或测试失败。

</system-reminder>
```

如果当前 run 没有任何可见 skill（比如 `/skills` root 被隐藏，或者 `visible_skill_names` 为空），runtime 不会把这段摘要注入 prompt，也不会把 `Skill` 工具注册给模型。

### 第二步：通过 Skill 工具加载完整内容

当模型判断当前任务需要某个 skill 时，它会调用内置的 `Skill` 工具并传入 skill 名称，例如 `Skill(skill="data:excel")`。runtime 收到这个调用后，先检查请求的 skill 是否在当前 run 的可见列表中——如果不在，直接返回错误 `"Skill not assigned to current agent"`，不会泄露其他 skill 的信息。检查通过后，runtime 从 catalog 中读取 SKILL.md 的完整内容，同时标记当前 thread 已经加载过这个 skill（供后续物化逻辑使用），最后把结果按固定格式返回给模型：

```
Launching skill: data:excel

Base directory for this skill: /skills/data:excel

<SKILL.md 完整内容>
```

其中 `Base directory` 这一行是关键信息。它告诉模型：这份 skill 的入口说明已经拿到了，如果 SKILL.md 正文中引用了 `references/`、`scripts/`、`assets/` 下的文件，模型应该通过 `/skills/data:excel/...` 这个路径去继续读取。

### 第三步：通过 /skills/ 路径访问 skill 资源

模型拿到 base directory 后，就可以按照 SKILL.md 中的指引，通过 `/skills/` 路径继续读取 skill 包内的文件，比如 `/skills/data:excel/references/spec.md` 或 `/skills/data:excel/scripts/analyze.py`。

这里需要注意一点：`/skills/` 路径并不是 catalog 源目录的直接映射，而是当前 thread 可见 skill 的副本视图。当模型第一次请求某个 skill 的文件时，`ComputerRuntime` 会把这个 skill 的整个目录从 catalog 源复制到当前 thread 的独立副本目录中。之后这个 thread 对 `/skills/` 下该 skill 的所有读写操作都发生在副本上，不会影响到 catalog 中的原始文件。这种设计保证了多个 thread 可以同时使用同一个 skill 而不会互相干扰。

此外，`WorldView.resolve()` 在解析 `/skills/` 路径时会检查请求的 skill 名称是否属于当前 run 的可见列表。模型不能通过路径遍历来读取自己无权访问的其他 skill，这是 skill 级别的隔离机制。

## 配置

```yaml
runtime:
  profiles:
    aca:
      skills:
        - data:excel
        - debugging
  filesystem:
    skill_catalog_dirs:
      - "./my-skills"              # project scope
      - "~/.agents/skills"         # user scope
```

---

## 附录

### SkillCatalog

统一查询入口，保留全部候选项，按规则选择正式生效的那一份。

```python
class SkillCatalog:
    def reload(self)           # 重新扫描全部
    def get(self, name)        # 按优先级取一条 manifest
    def read(self, name)       # 读取完整 SkillPackageDocument
    def visible_skills(profile)  # 按 profile.skills 过滤
```

`list_all()` 返回全部候选项，`get()` / `read()` 只返回同名中优先级最高的那一条。

### SkillPackageManifest

贯穿发现到执行的核心数据结构（`slots=True`，字段即全部状态）：

```python
@dataclass(slots=True)
class SkillPackageManifest:
    skill_name: str              # runtime 主键，来自目录路径
    scope: str                   # "project" | "user"
    description: str             # 简短说明
    host_skill_file_path: str    # SKILL.md 的宿主机绝对路径
    argument_hint: str
    disable_model_invocation: bool
    metadata: dict
```

`skill_name` 是寻址主键（工具参数、`/skills/` 路径、prompt 摘要都用它）。`display_name` 属性来自 `metadata["display_name"]`（即 frontmatter 的 `name`），仅用于控制面展示，为空则回退 `skill_name`。

派生属性：

| 属性 | 计算方式 | 使用场景 |
|------|----------|----------|
| `host_skill_root_path` | `Path(host_skill_file_path).parent` | 物化复制时的源目录 |
| `display_name` | `metadata.get("display_name") or skill_name` | 控制面展示 |
| `has_references` | `(root / "references").is_dir()` | payload 中标记是否有参考资源 |
| `has_scripts` | `(root / "scripts").is_dir()` | 同上 |
| `has_assets` | `(root / "assets").is_dir()` | 同上 |

### SkillPackageDocument

在 manifest 基础上多带 SKILL.md 原始文本，只有 `Catalog.read()` 和 `Loader.read_document()` 返回：

```python
@dataclass(slots=True)
class SkillPackageDocument:
    manifest: SkillPackageManifest
    raw_markdown: str     # 含 frontmatter 的原始 SKILL.md
    body_markdown: str    # 去掉 frontmatter 后的正文
```

### 源码索引

| 文件 | 职责 |
|------|------|
| `src/acabot/runtime/skills/package.py` | 数据结构、SKILL.md 解析 |
| `src/acabot/runtime/skills/loader.py` | 文件系统扫描、命名推导 |
| `src/acabot/runtime/skills/catalog.py` | 统一查询入口、同名选择、可见性过滤 |
| `src/acabot/runtime/bootstrap/config.py` | 扫描目录解析、scope 推断 |
| `src/acabot/runtime/bootstrap/builders.py` | `build_skill_catalog()` 组件组装 |
| `src/acabot/runtime/builtin_tools/skills.py` | Skill 工具注册、可见性检查、结果格式化 |
| `src/acabot/runtime/computer/world.py` | `/skills/` 路径映射、跨 skill 读取防护 |
| `src/acabot/runtime/computer/runtime.py` | skill 物化（catalog 源 → thread 副本） |
