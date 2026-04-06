
## 什么是 Impeccable

### 1. 技能（Skill）：`frontend-design`

这是 Impeccable 的核心。当你要构建网页组件、页面或应用时，AI 会调用这个技能来指导设计方向。它包含 7 个专业参考文件：

| 参考文件 | 内容 |
|---------|------|
| `typography.md` | 字体系统、字体搭配、模块化比例、OpenType 特性 |
| `color-and-contrast.md` | OKLCH 色彩空间、 tint 中性色、暗黑模式、无障碍对比度 |
| `spatial-design.md` | 间距系统、网格布局、视觉层次 |
| `motion-design.md` | 缓动曲线、错开动画、减少动画偏好 |
| `interaction-design.md` | 表单设计、焦点状态、加载模式 |
| `responsive-design.md` | 移动优先、流式设计、容器查询 |
| `ux-writing.md` | 按钮标签、错误提示、空状态文案 |

### 2. 命令（Commands）：20 个设计导向指令

这些是用户可以直接调用的命令，格式为 `/命令名`（Codex CLI 上是 `/prompts:命令名`）。

### `/teach-impeccable` — 一次性设置
**用途**：首次使用时，收集你的项目设计上下文（目标用户、品牌调性等），保存到配置文件。

```bash
/teach-impeccable    # 启动上下文收集向导
```
*何时使用*：第一次在项目中使用 Impeccable 时，运行一次即可。


### `/audit` — 技术质量检查
**用途**：对界面进行全面的技术审查，包括无障碍、性能、响应式等方面，输出审查报告（不直接修改代码）。

```bash
/audit blog              # 审计博客首页 + 文章页
/audit dashboard         # 检查仪表盘组件
/audit checkout flow     # 聚焦结算流程
```

*何时使用*：在动手修改之前，先了解有哪些问题需要修复。


### `/critique` — UX 设计评审
**用途**：从用户体验角度评审界面，包括视觉层次、信息架构、情感共鸣、认知负荷等。

```bash
/critique landing page    # 评审落地页 UX
/critique onboarding      # 检查新手引导流程
```

*何时使用*：需要设计反馈而非技术修复时。


### `/normalize` — 对齐设计系统
**用途**：将界面元素对齐到统一的设计规范——应用设计 token、修复间距、统一组件样式。

```bash
/normalize blog           # 应用设计 token，修复间距不一致
/normalize buttons       # 标准化按钮样式
```

*何时使用*：`/audit` 之后，修复不一致问题。


### `/polish` — 交付前最终打磨
**用途**：上线前的最后一遍检查，处理对齐、间距、一致性、微细节问题。

```bash
/polish feature modal     # 清理弹窗细节
/polish settings page     # 最终检查设置页
```

*何时使用*：部署到生产环境之前的最后一步。


### `/distill` — 精简到本质
**用途**：移除不必要的复杂性，让界面更清晰、更有焦点。

```bash
/distill sidebar          # 精简侧边栏
/distill hero section     # 简化首屏区域
```

*何时使用*：界面过于复杂或信息过载时。

### `/clarify` — 改善 UX 文案
**用途**：改进按钮标签、错误提示、空状态文案等不够清晰的文字。

```bash
/clarify form errors      # 改善表单错误提示
/clarify empty states     # 改进空状态文案
```

*何时使用*：用户反馈界面文案令人困惑时。


### `/optimize` — 性能优化
**用途**：提升加载速度、渲染性能、动画流畅度，减少包体积。

```bash
/optimize images          # 优化图片加载
/optimize bundle          # 减少 JS/CSS 体积
```

*何时使用*：页面加载慢或交互卡顿时。


### `/harden` — 强化健壮性
**用途**：添加错误处理、i18n 支撑、边界情况管理，让界面更健壮。

```bash
/harden forms             # 为表单添加完整错误处理
/harden i18n              # 补充国际化支撑
```

*何时使用*：需要处理边界情况或准备全球化发布时。


### `/animate` — 添加目的性动效
**用途**：添加有意义的动画和微交互，提升用户体验。

```bash
/animate page transitions  # 添加页面切换动画
/animate button feedback   # 完善按钮反馈动画
```

*何时使用*：界面缺乏活力或需要引导用户注意力时。


### `/colorize` — 引入战略性配色
**用途**：为单调的界面添加有策略意义的色彩。

```bash
/colorize dashboard       # 为仪表盘添加品牌色系
```

*何时使用*：界面色彩过于单调或缺乏品牌一致性时。


### `/bolder` — 增强视觉冲击力
**用途**：让平淡无聊的设计变得更醒目、更有力量感。

```bash
/bolder call to action    # 加强行动号召区域的视觉冲击
```

*何时使用*：设计风格太保守、缺乏吸引力时。


### `/quieter` — 降低视觉噪音
**用途**：让过于激进张扬的设计变得更沉稳、精致。

```bash
/quieter landing page     # 降低落地页的视觉噪音
```
*何时使用*：界面过于花哨或杂乱时。


### `/delight` — 添加惊喜时刻
**用途**：加入有趣的微交互、彩蛋动画，让用户感到愉悦。

```bash
/delight success state    # 成功状态添加惊喜动效
```

*何时使用*：需要提升用户体验的愉悦感时。


### `/extract` — 提取为复用组件
**用途**：将重复的 UI 模式提取为可复用组件，构建设计系统。

```bash
/extract card patterns    # 提取卡片组件
```

*何时使用*：发现重复代码需要组件化时。


### `/adapt` — 适配不同设备
**用途**：让界面适配不同的屏幕尺寸和设备场景。

```bash
/adapt mobile             # 优化移动端适配
```

*何时使用*：需要在不同设备上保持体验一致时。


### `/onboard` — 设计新手引导
**用途**：设计空状态、首次使用引导、教程流程。

```bash
/onboard new user         # 设计新用户引导流程
```

*何时使用*：需要设计注册/激活流程时。


### `/typeset` — 完善字体排版
**用途**：修复字体选择、层级关系、尺寸比例等排版问题。

```bash
/typeset article page     # 优化文章页排版
```

*何时使用*：文字层次混乱或字体选择不当时。


### `/arrange` — 优化布局与间距
**用途**：改善布局结构、间距节奏、视觉层次感。

```bash
/arrange dashboard grid   # 优化仪表盘网格布局
```

*何时使用*：布局感觉不对劲或间距单调时。


### `/overdrive` — 添加技术极限特效
**用途**：加入技术上前沿的特效，如着色器、弹簧物理、滚动驱动动画等。

```bash
/overdrive hero section   # 为首屏添加炫酷特效
```

*何时使用*：需要让人"哇"的时刻。



## 典型工作流

### 完整流程：审计 → 修复 → 打磨

```bash
/audit /normalize /polish blog    # 完整流程：发现问题 → 修复 → 收尾
```

### 组合使用

```bash
/critique /harden checkout        # UX 评审 + 添加错误处理
/optimize /animate /polish modal  # 优化性能 + 加动画 + 打磨
```

---


## 反模式（重要）

Impeccable 明确告诉你**不该做什么**：

- ❌ 不要用 Inter、Roboto、Arial 等烂大街的字体
- ❌ 不要在彩色背景上用灰色文字（会看起来褪色）
- ❌ 不要用纯黑（#000）或纯白（#fff）——总是要 tint 一下
- ❌ 不要把所有东西都包在卡片里，更不要卡片嵌套卡片
- ❌ 不要用 bounce/elastic 缓动（看起来过时了）
- ❌ 不要用紫色到蓝色的渐变 + 暗黑背景（AI 色盘）
- ❌ 不要居中一切——左对齐 + 不对称布局更有设计感

---

## 快速开始

1. **安装**：下载对应工具的 ZIP，解压到项目根目录
2. **初始化**：运行 `/teach-impeccable`，回答几个关于项目的问题
3. **使用**：开始你的设计工作，AI 会自动应用 Impeccable 的设计原则
4. **迭代**：`/audit` 发现问题 → `/normalize` 修复 → `/polish` 收尾

---

## 小贴士

- **大多数命令接受可选参数**指定聚焦区域：`/audit header`、`/polish checkout-form`
- **可以组合使用**：用空格分隔多个命令，如 `/audit /normalize /polish blog`
- **Codex CLI 使用不同语法**：命令格式为 `/prompts:audit`、`/prompts:polish` 等
- **先审计再动手**：`/audit` 给出的是不带修改的纯报告，是最安全的第一步