# skill 机制

> [!note] skill 机制目前未彻底和 `## 2. skill 加载机制(以此为准)` 对齐

## 1. `skill` 是什么

> `skill` 是一个按目录组织的能力包。
> 有些能力不是一个函数，而是一整套“怎么做这件事”的包。

- 给模型一份任务说明
- 给模型一套工作步骤
- 给模型一组按需读取的参考资料
- 必要时再给它脚本和资源

这个能力包至少有：

- `SKILL.md`

还可以继续带：

- `references/`
- `scripts/`
- `assets/`


>[!question]skill 为什么单独存在

很多任务并不是“给一个 接口/tool 就够了”。

比如：
- 做某类固定格式分析
- 按一套流程处理某类文件
- 生成特定风格的输出

这类事情需要：

- 先看说明
- 再看参考资料
- 再按步骤操作
- 配合脚本和资源

## 2. skill 加载机制(以此为准)

1. runtime 先扫描 skill 目录，建立名字到文件的映射
    - 扫描指定目录里的 `SKILL.md`
    - `<project>/.agents/skills/**/SKILL.md`
    - `~/.agents/skills/**/SKILL.md`
    - `....`


2. 每个 `SKILL.md` 会被解析成一个 `SkillMeta`
    - 取 `frontmatter.name`，没有就用相对目录名推导
    - 例如 `foo/bar/SKILL.md -> foo:bar`
    - 同时保存 `filePath`、`description`、`scope`

3. 发请求前，runtime 把“有哪些 skill”暴露给模型
    - 放进system prompt的一个 `<system-reminder>`块里, 如下:
    ```
    <system-reminder>
    The following skills are available for use with the Skill tool:
    - frontend-design: ...
    - systematic-debugging: ...
    </system-reminder>
    ```

4. 模型看到的是 skill 名字和描述，不是路径
    - 它知道“可以调用哪个 skill”，但不知道文件路径，这没关系，因为路径不是它负责找

5. 模型要用 skill 时，直接调用 `Skill` 工具，只传名字
    - 像这样：
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
    - 返回内容本质上是：
    ```text
    Launching skill: frontend-design
    ```
    - 再附带一个额外文本块：
    ```text
    Base directory for this skill: /some/path/to/frontend-design

    ...SKILL.md 正文...
    ```
    - 模型后面读附件就靠这个 base dir

8. 后续附件不是自动加载的，是模型根据 `Base directory for this skill` 自己继续读
    - 如果正文里写：
        ```text
        Read references/style-doctrine.md first.
        Then inspect scripts/build.sh.
        ```
    - 模型就能推出：
    - `/some/path/to/frontend-design/references/style-doctrine.md`
    - `/some/path/to/frontend-design/scripts/build.sh`
    - 然后再调用普通文件工具去读

---

## 4. 当前代码里 skill 是怎么进 runtime 的

### 4.1 先被读进 `SkillCatalog`

当前 skill 的统一目录入口是：

- `SkillCatalog`

它会把 skill 目录扫出来，变成一组 manifest。
manifest 里会带：

- `skill_name`
- `display_name`
- `description`
- `root_dir`
- `skill_md_path`
- 是否有 `references / scripts / assets`

这一步表达的是：

> 系统先知道“有哪些 skill”，以及它们最小的摘要信息是什么。

### 4.2 profile 决定谁能看到哪些 skill

当前不是所有 agent 都能看到所有 skill。
真正决定可见性的还是 profile：

- `profile.skills`

也就是说，一个 skill 先存在于 catalog 里，然后再通过 profile 变成“当前 agent 可见”。

这一步表达的是：

> skill 先是全局能力包，再由 profile 决定当前 agent 能看到哪一部分。

### 4.3 当前 run 里还会再按 world 过滤一次

除了 profile 这层，当前 run 里还会再经过一次 world 可见性过滤。

也就是：

- profile 说这个 agent 理论上能看到哪些 skill
- 当前 `world_view` 再决定这次 run 里 `/skills` 根下到底能看到哪些

所以现在 skill 可见性已经不是单靠 profile 一层说了算，而是：

- profile
- world

两层一起决定。

## 5. 现在 skill 是怎么给模型看的

这部分是当前最容易让人误会的地方。

因为现在代码里其实是 **双轨**。

### 5.1 第一条线：skill 摘要会进 system prompt

当前 `ModelAgentRuntime` 会把可见 skill 的摘要拼进 system prompt。

也就是类似：

- `Available Skills:`
- `- skill_name: description`

这条线表达的是：

> 模型先知道“当前有哪些 skill 可以用”。

这一步很重要，因为它让 skill 先变成“模型脑子里的一份能力目录”，而不是一上来就把整份 `SKILL.md` 塞进去。

### 5.2 第二条线：当前代码里仍然保留了 `skill(name=...)` 这个工具

这是现在最需要说清楚的地方。

当前代码里仍然存在：

- builtin `skill` tool

它的行为是：

- 检查这个 skill 当前是不是可见
- 读取这个 skill 的 `SKILL.md`
- 把整份 markdown 返回给模型

所以今天的真实情况不是：

- skill 已经彻底只走 prompt 摘要 + `/skills/...` 文件读取

而是：

- prompt 摘要已经有了
- 但 `skill(name=...)` 这个旧入口还活着

这就是现在 skill 机制最明显的中间态。

## 6. `/skills/...` 这条线现在又是什么关系

前台 `computer` 现在已经支持：

- `/skills/...`

也就是说，模型理论上已经可以通过通用文件工具去读 skill 相关路径，比如：

- `/skills/foo/SKILL.md`
- `/skills/foo/references/...`
- `/skills/foo/scripts/...`
- `/skills/foo/assets/...`

而且这条线和 Work World 是对齐的。

这很关键，因为它意味着：

> skill 不一定必须继续靠专门工具读。

只要：

- prompt 里先暴露 skill 摘要
- `/skills/...` 路径是稳定的
- `read / bash` 这些通用工具可用

那模型其实已经有机会按更自然的方式使用 skill。
