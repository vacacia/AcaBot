# AstrBot 图片转述实现梳理

这份文档只记录我**实际查看过的 AstrBot 代码行为**，不写 AcaBot 方案，不做猜测。

参考源码根目录：

- `/home/acacia/mycode/ref/AstrBot`

本次重点查看了这些文件：

- `astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`
- `astrbot/builtin_stars/astrbot/process_llm_request.py`
- `astrbot/core/provider/entities.py`
- `astrbot/core/message/components.py`
- `astrbot/builtin_stars/astrbot/long_term_memory.py`
- `dashboard/src/i18n/locales/zh-CN/features/config-metadata.json`

## 1. 当前消息里的图片是怎么进入 LLM 请求的

入口在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`

在构造 `ProviderRequest` 时，AstrBot 会遍历 `event.message_obj.message`：

- 遇到 `Image` 组件：
  - `await comp.convert_to_file_path()`
  - 把返回的**本地文件路径**加入 `req.image_urls`
  - 同时往 `req.extra_user_content_parts` 里追加一段文本：
    - `"[Image Attachment: path {image_path}]"`
- 遇到 `File` 组件：
  - 取文件路径
  - 追加文本说明到 `extra_user_content_parts`

也就是说，AstrBot 这里**不是直接拿平台传上来的原始 URL 就结束**，而是先把图片统一规整成“可读的本地文件路径”。

## 2. AstrBot 的图片输入不是只吃 URL，它会做统一转换

图片组件定义在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/core/message/components.py`

`Image.convert_to_file_path()` 的行为很明确：

- `file:///...` -> 直接返回本地路径
- `http/https` -> 先下载图片，再返回下载后的本地路径
- `base64://...` -> 写入临时 jpg 文件，再返回本地路径
- 普通本地路径 -> 直接返回绝对路径

这说明 AstrBot 的图片输入链路本质上是：

1. 先把图片统一转成**本地文件**
2. 再把本地文件交给后续 provider/request 组装逻辑

不是“平台给了一个 URL，然后原样扔给模型”。

## 3. ProviderRequest 最终怎么把图片装配进消息

核心代码在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/core/provider/entities.py`

`ProviderRequest` 里有两个和图片相关的字段：

- `image_urls: list[str]`
- `extra_user_content_parts: list[ContentPart]`

`assemble_context()` 的行为：

1. 先放 prompt 文本
2. 再放 `extra_user_content_parts`
3. 最后处理 `image_urls`

处理 `image_urls` 时：

- 如果是 `http`，会先下载图片
- 如果是 `file:///`，读取本地文件
- 如果是普通本地路径，直接读文件
- 之后统一转成：
  - `data:image/jpeg;base64,...`
- 再塞进 OpenAI 风格的 content blocks：
  - `{"type": "image_url", "image_url": {"url": image_data}}`

所以 AstrBot 当前图片输入的真实实现不是“给模型一个网络 URL”，而是：

- **把图片转成 base64 data URI，再作为多模态内容块发给模型**

## 4. 默认图片转述模型是怎么配、怎么用的

配置元数据在：

- `/home/acacia/mycode/ref/AstrBot/dashboard/src/i18n/locales/zh-CN/features/config-metadata.json`

这里能看到两组关键配置：

### 4.1 通用配置

- `provider_settings.default_image_caption_provider_id`
  - 文案：`默认图片转述模型`
- `provider_settings.image_caption_prompt`
  - 文案：`图片转述提示词`

### 4.2 长期记忆 / 群聊相关配置

- `provider_ltm_settings.image_caption`
  - 文案：`自动理解图片`
- `provider_ltm_settings.image_caption_provider_id`
  - 文案：`群聊图片转述模型`

也就是说，AstrBot 不只是“有一个 vision/chat 模型”，它确实单独做了图片转述模型配置。

## 5. 当前请求里的图片转述是怎么发生的

逻辑在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/builtin_stars/astrbot/process_llm_request.py`

关键流程：

1. 从配置里取：
   - `default_image_caption_provider_id`
   - `image_caption_prompt`
2. 如果当前 `req.image_urls` 非空，并且配置了转述 provider：
   - 调 `_request_img_caption(...)`
   - 本质上执行：
     - `prov.text_chat(prompt=img_cap_prompt, image_urls=image_urls)`
3. 如果拿到 caption：
   - 往 `req.extra_user_content_parts` 追加：
     - `<image_caption>...</image_caption>`
   - 然后把：
     - `req.image_urls = []`

这说明 AstrBot 当前的“图片转述”策略是：

- **先单独调用一个 provider 做 caption**
- **caption 成功后，把图片替换成文本说明**
- **原始图片不再继续给主请求**

注意一点：前面 `internal.py` 里已经加过

- `[Image Attachment: path ...]`

所以当图片转述启用时，主请求里通常会同时看到：

- 一条图片路径说明文本
- 一条 `<image_caption>...</image_caption>` 文本

而不是只剩纯 caption。

## 6. reply 引用消息里的图片怎么处理

同样在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/builtin_stars/astrbot/process_llm_request.py`

reply 处理逻辑是：

1. 从当前消息里找 `Reply` 组件
2. 先取引用消息的纯文本：
   - `quote.message_str`
3. 再看 `quote.chain` 里有没有 `Image`
4. 如果有图片：
   - 优先使用 `default_image_caption_provider_id`
   - 没配就退回当前正在使用的 provider
   - 调：
     - `prov.text_chat(prompt="Please describe the image content.", image_urls=[await image_seg.convert_to_file_path()])`
5. 得到结果后，把它追加成一段文本：
   - `[Image Caption in quoted message]: ...`
6. 最后把整段引用内容包成：
   - `<Quoted Message> ... </Quoted Message>`
   - 放进 `req.extra_user_content_parts`

几个重要结论：

- AstrBot 的引用消息图片**不是直接复用历史上下文里的旧文本**
- 它是**当前轮临时重新处理 reply 内容**
- 引用图片 caption 的 prompt 是**硬编码**
  - `"Please describe the image content."`
- 这里同样调用了 `convert_to_file_path()`，也就是仍然走“图片先统一成本地路径”的套路

## 7. 主模型不支持图片时，AstrBot 还有一层 provider 模态兜底

逻辑在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`

`_modalities_fix()` 会检查 provider 的 `modalities`：

- 如果当前 provider 不支持 image：
  - 把 `req.image_urls` 清空
  - 往 `req.prompt` 里补 `[图片]` 占位符

这说明 AstrBot 的整体策略是两层：

1. **优先用图片本体**（`req.image_urls` -> 多模态输入）
2. 如果 provider 明确不支持 image：
   - 就退回成纯文本占位符
3. 如果又配置了图片转述 provider：
   - `process_llm_request.py` 会更早把图片转成 `<image_caption>...</image_caption>`

换句话说，AstrBot 的“图片能不能给主模型看”和“要不要先做 caption”是两条叠加链，不是一条简单分支。

## 8. 长期记忆里的图片转述是另一套

逻辑在：

- `/home/acacia/mycode/ref/AstrBot/astrbot/builtin_stars/astrbot/long_term_memory.py`

这里会额外读取：

- `provider_ltm_settings.image_caption`
- `provider_ltm_settings.image_caption_provider_id`
- `provider_settings.image_caption_prompt`

如果开启了长期记忆图片理解：

- 会为群聊消息中的图片单独调用 `get_image_caption(...)`
- 把结果拼进长期记忆文本

所以 AstrBot 不是只有“请求前图片转述”一处，**长期记忆也单独有图片 caption 配置和调用链**。

## 9. 基于实际代码的结论

从我实际读到的代码看，AstrBot 当前图片处理实现有这些明确特征：

1. **图片输入先统一规整**
   - 不是只依赖平台原始 URL
   - 会下载 / 解 base64 / 转本地路径

2. **主请求支持真正多模态**
   - `ProviderRequest.assemble_context()` 会把图片编码成 base64 data URI
   - 再塞进 content blocks

3. **图片转述模型是独立配置**
   - `default_image_caption_provider_id`
   - `image_caption_prompt`

4. **reply 图片不是“历史消息复用”，而是当前轮额外解析**
   - 文本和图片都在当前轮重新组装成 `<Quoted Message>`

5. **长期记忆里的图片理解是另一条配置链**
   - 不是简单复用主请求的图片转述逻辑

## 10. 这次文档没有写的内容

这次我**没有**继续深入每个 provider source 的 HTTP 请求细节，也没有把每个平台适配器都逐个读完。  
但对“图片如何进入请求、如何 caption、如何处理 reply、是否只靠 URL”这几个关键问题，上面这些文件已经足够得出结论。
