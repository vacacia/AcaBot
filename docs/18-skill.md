
# 1. `skill` 是什么(不准修改)

> `skill` 是一个按目录组织的能力包。
> 有些能力不是一个函数，而是一整套“怎么做这件事”的包。

- 给模型一份任务说明
- 给模型一套工作步骤
- 给模型一组按需读取的参考资料
- 必要时再给它脚本和资源

这个能力包至少有: 

- `SKILL.md`

还可以继续带: 

- `references/`
- `scripts/`
- `assets/`


>[!question]skill 为什么单独存在

很多任务并不是“给一个 接口/tool 就够了”。

比如: 
- 做某类固定格式分析
- 按一套流程处理某类文件
- 生成特定风格的输出

这类事情需要: 

- 先看说明
- 再看参考资料
- 再按步骤操作
- 配合脚本和资源

# 2. skill 加载机制设计(以此为准)(不准修改)

1. runtime 先扫描 skill 目录，建立名字到文件的映射
    - 扫描指定目录里的 `SKILL.md`
    - `<project>/.agents/skills/**/SKILL.md`
    - `~/.agents/skills/**/SKILL.md`
    - `....`


2. 每个 `SKILL.md` 会被解析成一个 `SkillMeta`
    - 取 `frontmatter.name`，没有就用相对目录名推导
    - 例如 `foo/bar/SKILL.md -> foo:bar`
    - 同时保存 `filePath`、`description`、`scope`(project/user)
    - 这里扫描的是"设置的全部skill目录下的全部skill", 不要按 name/scope 等过滤
    - 实际使用时, 才会根据"配置里的skill可见性", "scope里project优先级大于user", 来过滤skill, 然后再注入 prompt
    ```
    name: string    # frontmatter 里的 name, 没有就用相对目录推导, 例如 .../skills/foo/bar/SKILL.md -> foo:bar
    scope: 'project' | 'user'   # 根据来源判断: 全局 skills 目录是 user; 项目 skills 是 project
    filePath: string    # SKILL.md 的绝对路径
    description: string # frontmatter 的 description
    argumentHint?: string   # 取 frontmatter 的 argument-hint, 没有就不填
    disableModelInvocation?: boolean
    ```

3. 发请求前，runtime 把“有哪些 skill”暴露给模型
    - 放进system prompt的一个 `<system-reminder>`块里, 如下:
    ```
    <system-reminder>
    The following skills are available for use with the Skill tool:

    - frontend-design: Create distinctive, production-grade frontend interfaces with high design quality.
    - systematic-debugging: Use when encountering any bug, test failure, or unexpected behavior.
    - test-driven-development: Use when implementing any feature or bugfix, before writing implementation code.
    </system-reminder>
    ```

4. 模型看到的是 skill 名字和描述，不是路径
    - 它知道“可以调用哪个 skill”，但不知道文件路径，这没关系，因为路径不是它负责找

5. 模型要用 skill 时，直接调用 `Skill` 工具，只传名字
    - 像这样: 
    ```json
    {
        "name": "Skill",
        "input": {
        "skill": "frontend-design"
        }
    }
    ```
    - `Skill` 的 schema 只要求一个 `skill` 字段

6. runtime 收到 `Skill(skill="frontend-design")` 后，自己按名字找文件
    - 取到 `meta.filePath`
    - 再去读那个 `SKILL.md`

7. 读完 `SKILL.md` 后，runtime 不只返回正文，还会把 skill 基目录一并返回给模型
    - 返回内容本质上是: 
    ```text
    Launching skill: frontend-design
    ```
    - 再附带一个额外文本块: 
    ```text
    Base directory for this skill: /some/path/to/frontend-design

    ...SKILL.md 正文...
    ```
    - 模型后面读附件就靠这个 base dir

8. 后续附件不是自动加载的，是模型根据 `Base directory for this skill` 自己继续读
    - 如果正文里写: 
        ```text
        Read references/style-doctrine.md first.
        Then inspect scripts/build.sh.
        ```
    - 模型就能推出: 
    - `/some/path/to/frontend-design/references/style-doctrine.md`
    - `/some/path/to/frontend-design/scripts/build.sh`
    - 然后再调用普通文件工具去读

---
# 实际代码
## 当前代码里 skill 是怎么进 runtime 的
### 先被读进 `SkillCatalog`

skill 的统一目录入口是: `SkillCatalog`
现在由 `runtime.filesystem.skill_catalog_dirs` 控制要扫描哪些 skill 根目录。

规则是:

- 相对路径, 例如 `./skills`、`./agent/skills`, 算 `project`
- `~` 路径和根目录绝对路径, 算 `user`
- 每个目录都会递归找 `**/SKILL.md`

如果配置没写, runtime 默认会扫常用目录:

- `./.agents/skills`
- `~/.agents/skills`

这里当前已经和第 2 节对齐的部分是:

- 扫描阶段会先把所有扫描到的 skill metadata 都收进来
- 不会在扫描阶段先按同名过滤掉 project / user 的另一份 skill
- 每条 metadata 会显式保存 `scope`
- 宿主机真源文件路径会显式保存成 `host_skill_file_path`
- `skill_name` 继续用相对目录名推导，像 `foo/bar/SKILL.md -> foo:bar`
- `argument-hint` 和 `disable-model-invocation` 也会进入 metadata

### 4.2 真正使用时才按 scope 和可见性选 skill

当前代码里，同名 skill 会先一起保留在 catalog 里。
真正给模型看和真正执行 `Skill(skill="...")` 的时候，才会按当前规则选出最后那一份:

- 先看 profile 里这个 skill 名是不是可见
- 再看当前 run 的 `/skills` world 可见性
- 同名时 project 优先级高于 user

所以今天真正的过滤时机不是扫描阶段，而是:

- prompt 注入前
- `Skill` 工具真正读取前

### 4.3 profile 和 world 一起决定可见性

当前不是所有 agent 都能看到所有 skill。
真正进入一次 run，要过两层: 

- `profile.skills`
- 当前 `world_view` 的 `/skills` 可见性

也就是说: 

- profile 决定这个 agent 理论上能看到哪些 skill
- world 再决定这次 run 里 `/skills` 根下到底暴露哪些 skill

所以今天 skill 可见性是: 

- catalog
- profile
- world

一起决定。

## 5. 现在 skill 是怎么给模型看的

### 5.1 skill 摘要会先进 system prompt

当前 `ModelAgentRuntime` 会把可见 skill 的摘要拼进 system prompt，
而且格式已经对齐成第 2 节说的 `<system-reminder>`: 

```text
<system-reminder>
The following skills are available for use with the Skill tool:
- sample_configured_skill: ...
- frontend:design: ...
</system-reminder>
```

也就是说，模型现在先看到的是: 

- skill 名字
- skill 描述

而不是先看到物理路径。

### 5.2 当前工具是 `Skill(skill=...)`

前台现在给模型暴露的是 builtin: `Skill`

它的 schema 只要求: `skill`

模型现在用的是: `Skill(skill="frontend-design")`

### 5.3 `Skill` 返回的已经是“入口 + 基目录 + 正文”

当前 `Skill` 工具读完 `SKILL.md` 后，会返回固定格式的文本: 

```text
Launching skill: frontend-design

Base directory for this skill: /skills/frontend-design

...SKILL.md 正文...
```

这里的 `Base directory` 在 AcaBot 当前实现里，用的是前台真正能继续访问的 Work World 路径: 

- `/skills/<skill_name>`

不是宿主机绝对路径。

## 6. `/skills/...` 这条线现在是什么关系

前台 `computer` 现在已经支持稳定的: 

- `/skills/...`

也就是说，模型调用完 `Skill` 之后，可以继续直接读: 

- `/skills/foo/SKILL.md`
- `/skills/foo/references/...`
- `/skills/foo/scripts/...`
- `/skills/foo/assets/...`

这条线现在已经和 Work World 对齐了。

所以今天 skill 的正式使用链路就是: 

1. prompt 先暴露 skill 摘要
2. 模型调用 `Skill(skill="...")`
3. runtime 返回 `Launching skill` + `Base directory for this skill: /skills/...` + `SKILL.md` 正文
4. 模型沿 `/skills/...` 继续读 references / scripts / assets

也就是说，当前 skill 已经收成一条统一的正式主线。
