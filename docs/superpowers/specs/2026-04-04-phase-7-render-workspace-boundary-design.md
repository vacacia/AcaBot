# Phase 7 设计：Render 可读性与 Workspace 边界

**日期：** 2026-04-04  
**状态：** 设计已确认，待进入 planning  
**读者：** runtime / control plane / WebUI 开发者  
**目标：** 在不扩大范围、不重做既有消息主线的前提下，补齐 Phase 7 的两个遗留闭环。

---

## 1. 范围

Phase 7 只收两件事：

1. 让 `message.send.render` 生成的图片在真实 QQ 客户端里可读，并留下正式人工验收记录。
2. 让 `/workspace` 的模型工作语义、QQ 本地文件发送规则、runtime 内部 artifact 边界保持一致。

本期明确不做：

- 不新增消息能力
- 不重做 message tool schema
- 不重做 render 视觉风格
- 不做 host shell 到 `/workspace` 的虚拟化
- 不把 QQ 本地文件规则直接推广到其他平台
- 不重做 `message -> Outbox -> Gateway` 主线

---

## 2. 最终设计

### 2.1 Render 可读性

#### 目标
把 render 可读性问题定义为**像素密度问题**，而不是视觉风格问题。

#### 必须完成的改动
- 把下面两个 render 默认值从硬编码改成 runtime 正式配置：
  - `render_width`
  - `render_device_scale_factor`
- 在 WebUI 中提供这两个值的**全局默认配置**入口。
- 保持既有 render 主线不变：
  - 模型提供待渲染内容
  - render service 在 runtime 内部完成渲染
  - outbox 物化为图片 segment
  - gateway 发送最终图片

#### 非目标
- 不重做 render 主题风格
- 不重排内容密度
- 不做 session 级 render 覆盖

#### 验收规则
只有当真实 QQ 客户端确认下面 8 类内容都可读时，render 才算完成：
- 标题
- 普通段落
- 列表
- 行内公式
- 块公式
- 代码块
- 引用块
- 表格

---

### 2.2 Workspace 与 Runtime 边界

#### 模型工作契约
模型的所有工作都在 `/workspace` 中完成。

这条规则写入 **system prompt**。

#### QQ 本地文件发送规则
当模型向 QQ 发送本地文件时：
- 文件必须位于 `/workspace` 下
- 路径必须使用**相对路径**表达

这条规则写入 **message 工具契约 / 工具说明**，不写入 system prompt。

#### 发送其他路径文件的方式
如果模型确实能看到其他路径的文件，并且确实想发送它，那么它必须：
1. 先把文件移动或复制到 `/workspace`
2. 再通过 message 工具使用相对路径发送

#### Render 例外
`message.send.render` **不属于**“模型自己挑选一个本地文件发送”。

因此：
- render artifact 可以继续留在 runtime 内部 artifact 存储中
- render artifact 不需要搬到 `/workspace`
- render artifact 不受上面的 QQ 本地文件发送规则约束

#### 明确非目标
host backend 下 shell 看到真实宿主机路径，不属于本期要解决的问题。

---

## 3. 交付面

### 3.1 Runtime / Config
runtime 里不能再硬编码：
- render width
- render device scale factor

这两个值都必须成为正式 runtime 配置项。

### 3.2 WebUI / Control Plane
WebUI 必须提供一个简单的可编辑入口，用于：
- 查看 render width
- 修改 render width
- 查看 render device scale factor
- 修改 render device scale factor
- 保存这两个全局默认值

本期不要求做复杂预览，只要求具备查看、编辑、保存能力。

### 3.3 Prompt 与工具契约
- **System prompt：** 明确所有工作都在 `/workspace` 中完成
- **Message 工具契约：** 明确 QQ 本地文件发送只接受 `/workspace` 下的文件，且路径必须是相对路径

### 3.4 文档
相关文档必须统一到最终口径：
- `/workspace` 是模型侧工作语义
- 宿主机真实路径是 runtime 内部实现细节
- render artifact 是 runtime 内部发送产物，不是模型手动选择的本地文件

---

## 4. 验证与 Artifacts

Phase 7 只有在下面几类交付都存在时才算完成。

### 4.1 工程完成
- render width 已可配置
- render device scale factor 已可配置
- WebUI 可编辑这两个值
- prompt 与 message 工具契约已同步更新
- 相关 docs 已同步更新

### 4.2 真实 QQ 验收记录
必须形成正式 phase artifact，至少记录：
- 本次验收使用的 render 配置值
- 验收时间
- 使用的客户端 / 环境
- 8 类内容各自的可读性结论
- 必要截图或说明
- 最终通过 / 不通过结论

### 4.3 通过条件
Phase 7 通过的条件是：
- 新配置链路可用
- WebUI 配置链路可用
- prompt / 工具契约 / docs 口径一致
- 真实 QQ 客户端验收记录证明 8 类内容全部可读

---

## 5. 预期涉及区域

implementation plan 应预期覆盖下面这些区域：

- render runtime
- runtime config / control plane
- WebUI settings 入口
- system prompt 组装
- message 工具契约 / 工具说明
- 相关 docs
- phase 验收 artifacts

不应把实现扩大成与本期目标无关的大范围架构重构。

---

## 6. Planning 约束

把这份设计转成 implementation plan 时，应遵守下面这些约束：

- 保留既有 `message -> Outbox -> Gateway` 主线
- 把 render 视为 runtime 内部流程
- 不把本期扩成多平台文件发送设计
- 除非出现硬性阻塞，否则不引入 session 级 render 配置
- 只聚焦补齐已经明确识别出的 audit gap
