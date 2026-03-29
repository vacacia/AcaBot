# Ref 项目前端页面与控制台调研

这份文档现在只保留对 AcaBot 重写后台控制台真正有用的参考。

本轮最终只保留两个项目：

- `AstrBot`
- `nekro-agent`

其他参考项目先全部拿掉，不继续干扰当前前端信息架构判断。

## 先讲结论

这轮最该学的不是具体样式，而是页面边界。

### 1. 只看后台控制台，不看聊天工作区

AcaBot 当前阶段先把后台控制台做对。

聊天工作区以后再说。

所以这份文档里，`AstrBot` 的聊天工作区只作为旁证，不作为 AcaBot 当前直接参考目标。

### 2. 配置对象和运行数据必须严格分层

这是这轮最重要的结论。

不能把这些东西继续揉在一起：

- provider / preset / prompt 这种共享配置对象
- session / memory / logs / conversation data 这种运行时对象或运行数据
- plugin / skill / MCP / tool behavior 这种扩展能力对象

更合理的方式是：

- 一类对象一类页面
- 页面里只编辑这一类对象
- 运行数据和配置对象不要混页

### 3. 不要把所有配置都塞进同一页

一个页面里混太多对象，最后只会变成：

- 信息密度很高
- 用户不知道自己到底在改什么
- 修改后影响边界不清楚

更稳的结构是：

- 列表页
- 详情页
- 必要时加局部页签

### 4. `AstrBot` 的插件总页有参考价值，但不适合直接照搬

AstrBot 用一个总入口承接：

- 插件
- 插件市场
- MCP
- Skills
- 行为管理

这对 AstrBot 自己能成立，但对 AcaBot 来说有点牵强。

因为这几个对象虽然都能算“扩展生态”，但职责并不近：

- 插件是运行时扩展单元
- 插件市场是分发入口
- MCP 是外部能力接入
- Skills 是知识/能力包
- 行为管理更像命令和工具暴露层

对 AcaBot 更合适的做法是：

- 直接拆成独立页面

如果一定要在导航上给它们一个共同分组名，我更推荐：

- `扩展能力`

然后下面拆成子页面：

- `插件`
- `插件市场`
- `MCP`
- `技能`
- `工具与行为`

重点是：

- 导航上可以分组
- 页面上不要混页

## AstrBot

`AstrBot` 是这次最重要的参考对象。

不是因为它每一页都要抄，而是因为它已经把“后台控制台到底在管理什么对象”这件事做得比较清楚。

## AstrBot 顶层对象分层

从页面边界看，AstrBot 主要把后台对象拆成这些层：

- 平台接入
- 模型提供
- 配置文件
- 插件与扩展能力
- 知识资产
- 会话规则
- 历史对话数据
- 任务
- SubAgent
- 日志与追踪
- 系统维护

这套分法最值得学的地方是：

- 它不会把 `模型`、`会话规则`、`历史数据`、`日志` 放在同一个页面
- 它承认这些对象不是同一种东西

## AstrBot 里最值得参考的页面

这里只保留对 AcaBot 后台控制台最有用的页面。

### 机器人 `/platforms`

这个页面管的是平台接入。

可查看：

- 平台卡片
- 启用状态
- 运行状态
- webhook
- 平台日志

可配置：

- 新增平台
- 编辑平台
- 删除平台
- 启停平台
- 平台路由规则

最值得借鉴的点：

- 平台接入是独立对象
- 不和 session、模型、prompt 混页

### 模型提供商 `/providers`

这个页面管的是模型供应。

它最关键的参考价值不是 UI，而是模型对象分层：

- `provider source`
  - 管凭据、Base URL、供应商连接
- `provider instance`
  - 管具体模型实例

可查看：

- source 列表
- source 配置
- source 下的模型实例

可配置：

- 新增 source
- 编辑 source
- 拉取模型列表
- 手动补模型
- 启停/测试/删除模型实例

最值得借鉴的点：

- 模型供应层不要扁平化成一个大表
- 连接对象和模型对象要分层

这对 AcaBot 的：

- `model_provider`
- `model_preset`

非常有参考价值。

### 配置文件 `/config#normal` 和 `/config#system`

这个页面管的是全局配置模板和系统配置。

可查看：

- 当前配置文件
- 配置区块
- 搜索结果
- 未保存提示

可配置：

- 多配置文件切换
- 新建
- 重命名
- 删除
- 可视化编辑
- JSON 编辑

最值得借鉴的点：

- 系统配置和普通配置是控制面对象
- 页面里要明确未保存状态
- 编辑后最好配一个验证入口

### 插件 `/extension`

AstrBot 在这里做的是“大总页 + 多子标签”。

子层包括：

- 已安装插件
- 插件市场
- MCP
- Skills
- 管理行为

这一页的真正参考价值不是“合并成一页”，而是它承认这些对象彼此相关，但仍然做了明确子层拆分。

对 AcaBot 的结论是：

- 不建议做成一个大总页
- 但可以在导航上作为一个共同分组

### 知识库 `/knowledge-base`

这页最值得学的是结构，不是知识库本身。

它采用的是：

- 列表页
- 对象详情页
- 详情页内局部 tab

这很适合 AcaBot 以后承接复杂对象，比如：

- 长期记忆
- Session
- 世界/工作区对象

### 人格设定 `/persona`

这页最值得借鉴的是资源管理方式。

它不是一个长表单，而是：

- 左侧树
- 右侧卡片和详情

如果 AcaBot 以后有：

- 提示词资产
- persona
- 结构化知识材料

这种“资源树 + 详情”的模式很有用。

### 对话数据 `/conversation`

这页非常重要，因为它清楚地区分了：

- 运行历史数据
- 配置对象

可查看：

- 对话标题
- 对话 ID
- 平台
- session
- 创建/更新时间

可配置：

- 搜索
- 查看详情
- 改标题
- 删除
- 导出

最值得借鉴的点：

- 运行数据必须是独立页面
- 不能塞到 session 配置页里

### 自定义规则 `/session-management`

这页最关键的意义是：

- Session 级对象值得有自己的页面

可查看：

- 规则列表
- 规则标签
- 分组

可配置：

- 新建规则
- 批量修改
- 改 provider override
- 禁用插件
- 绑定知识库

对 AcaBot 的启发：

- Session 不应该只是模型页里的一个下拉框
- Session 是正式对象
- Session 页应该只管 Session 相关配置

### 未来任务 `/cron`

这页证明“任务”值得独立成对象。

不要把它混进系统页或者插件页。

### SubAgent `/subagent`

这页证明“SubAgent 编排”值得独立成对象。

不要把它混进模型页或者 Persona 页。

### 平台日志 `/console` 与追踪 `/trace`

这两个页面是非常标准的运行数据页。

它们再次说明：

- `日志`
- `追踪`

都属于运行时数据，不属于配置对象。

### 设置 `/settings`

这页的作用是系统维护。

它应该只放：

- 主题
- 备份
- API Key
- 重启
- 迁移

这说明：

- 系统维护能力应该收在系统页
- 不要和业务配置对象混页

## AstrBot 对 AcaBot 最有价值的 4 个点

### 1. 配置对象和运行数据严格分层

这是 AstrBot 最该学的地方。

可以粗分成两大类：

配置对象：

- 平台
- 模型供应
- 配置模板
- 插件与扩展能力
- Session 规则
- 任务
- SubAgent
- 系统维护配置

运行数据：

- 对话数据
- 日志
- Trace

这个分层很适合直接拿来做 AcaBot 的后台 IA。

### 2. Session 是正式对象

Session 不只是运行时顺手带出来的附属物。

它值得有自己的页面。

### 3. 复杂对象要走“列表页 -> 详情页 -> 局部 tab”

不要指望一个超级长表单吃掉所有复杂对象。

### 4. 扩展能力要拆对象，不要强混

AstrBot 已经做了子层拆分。  
AcaBot 应该比它再进一步，直接把不相关对象拆成不同页面。

## nekro-agent

`nekro-agent` 是这轮第二个有价值的参考。

它最有价值的地方，不是某一页长什么样，而是后台 IA 很稳。

## nekro-agent 的主要对象分层

主导航大致包括：

- `Dashboard`
- `Chat Channel`
- `User Manager`
- `Presets`
- `Plugins`
- `Logs`
- `Workspace`
- `Sandbox Logs`
- `Adapters`
- `Settings`
- `Commands`
- `Profile`
- `Cloud`

对 AcaBot 有帮助的不是这些名字本身，而是它明确把对象拆成了：

- 全局对象
- 会话/频道对象
- 工作区/执行环境对象
- 扩展对象
- 运维对象

## nekro-agent 最值得借鉴的点

### 1. 列表页 + 详情页 + 页签

这是它最稳的一点。

比如：

- 工作区对象
- 频道对象
- 插件对象
- 适配器对象

都会自然走到：

- 先看列表
- 再看详情
- 再按局部页签拆具体域

这特别适合 AcaBot 后续的：

- Session
- Long Term Memory
- Workspace / World / Computer

### 2. 全局对象、频道对象、工作区对象三层明显分开

它不会把这些对象硬塞一页：

- 系统配置
- 模型组
- 频道覆盖配置
- 工作区 memory / prompt / sandbox

这对 AcaBot 很重要，因为你现在正好最介意“页面到底该放什么对象”。

### 3. 云市场和本地配置分开

这说明：

- 市场
- 本地对象管理

是两种不同页面职责。

如果以后 AcaBot 做插件市场，这个点很好用。

## AcaBot 当前最该吸收的结论

### 1. 后台控制台先只做后台控制台

先不讨论聊天工作区。

当前后台控制台应该只负责：

- 配置对象
- 运行数据
- 运维入口

### 2. 页面应该按对象类型拆

直接照这个原则走：

共享配置对象页面：

- `平台`
- `模型供应商`
- `模型预设`
- `提示词`
- `管理员`

扩展能力页面：

- `插件`
- `插件市场`
- `MCP`
- `技能`
- `工具与行为`

运行时与数据页面：

- `Session`
- `记忆`
- `对话数据`
- `日志`
- `追踪`

系统维护页面：

- `系统`

### 3. `model_binding` 不应该停留在模型页

这个结论和你前面说的是一致的。

绑定关系应该跟着消费对象走：

- Session 用到的模型，在 `Session` 页配
- 长期记忆用到的模型，在 `记忆` 页配
- 全局系统能力用到的模型，在对应系统页配

模型页只该负责：

- `model_provider`
- `model_preset`

### 4. 如果要给扩展相关对象一个共同导航分组名

我推荐：

- `扩展能力`

这个名字比把它们硬塞成一个页面更稳。

因为它表达的是：

- 这是一组相关对象的导航分组

而不是：

- 这几个对象应该被编辑在同一个页面里

## 证据文件

### AstrBot

- [MainRoutes.ts](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/router/MainRoutes.ts)
- [sidebarItem.ts](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/layouts/full/vertical-sidebar/sidebarItem.ts)
- [WelcomePage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/WelcomePage.vue)
- [PlatformPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/PlatformPage.vue)
- [ProviderPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/ProviderPage.vue)
- [ConfigPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/ConfigPage.vue)
- [ExtensionPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/ExtensionPage.vue)
- [KBList.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/knowledge-base/KBList.vue)
- [KBDetail.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/knowledge-base/KBDetail.vue)
- [PersonaPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/PersonaPage.vue)
- [ConversationPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/ConversationPage.vue)
- [SessionManagementPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/SessionManagementPage.vue)
- [CronJobPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/CronJobPage.vue)
- [SubAgentPage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/SubAgentPage.vue)
- [ConsolePage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/ConsolePage.vue)
- [TracePage.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/TracePage.vue)
- [Settings.vue](/home/acacia/AcaBot/ref/AstrBot/dashboard/src/views/Settings.vue)

### nekro-agent

- [navigation.tsx](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/config/navigation.tsx)
- [routes.ts](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/router/routes.ts)
- [detail.tsx](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/pages/workspace/detail.tsx)
- [ChatChannelDetail.tsx](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/pages/chat-channel/components/ChatChannelDetail.tsx)
- [system.tsx](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/pages/settings/system.tsx)
- [model_group.tsx](/home/acacia/AcaBot/ref/nekro-agent/frontend/src/pages/settings/model_group.tsx)
