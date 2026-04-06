/**
 * model_config_drafts 负责模型 / Provider 页面草稿相关的纯函数。
 *
 * 这些函数不依赖 Vue，方便单独测试：
 * - 生成文件系统安全的 preset id
 * - 在 litellm 探测结果到来时，只填充未被用户手动修改的字段
 * - 生成 Provider 保存载荷，避免把隐藏配置字段意外清空
 */

export type Capability =
  | 'tool_calling'
  | 'reasoning'
  | 'structured_output'
  | 'image_input'
  | 'image_output'
  | 'document_input'
  | 'audio_input'
  | 'audio_output'
  | 'video_input'
  | 'video_output'

export type PresetAutofillDraft = {
  context_window: string
  max_output_tokens: string
  capabilities: Capability[]
}

export type PresetTouchedState = {
  context_window: boolean
  max_output_tokens: boolean
  capabilities: boolean
}

export type LitellmModelInfo = {
  max_input_tokens?: number | null
  max_output_tokens?: number | null
  supports_vision?: boolean
  supports_function_calling?: boolean
  supports_reasoning?: boolean
  supports_response_schema?: boolean
  supports_audio_input?: boolean
  supports_audio_output?: boolean
}

export type HeaderEntry = { key: string; value: string }

export type ProviderSaveDraft = {
  provider_id: string
  name: string
  kind: string
  base_url: string
  api_key_env: string
  api_key: string
  anthropic_version: string
  api_version: string
  project_id: string
  location: string
  use_vertex_ai: boolean
  default_headers: HeaderEntry[]
  default_query: Record<string, unknown>
  default_body: Record<string, unknown>
}

export type ProviderSavePayload = {
  name: string
  kind: string
  base_url: string
  api_key_env: string
  api_key: string
  anthropic_version: string
  api_version: string
  project_id: string
  location: string
  use_vertex_ai: boolean
  default_headers: Record<string, string>
  default_query: Record<string, unknown>
  default_body: Record<string, unknown>
}

/**
 * 判断一个 ID 是否含有路径风险字符。
 */
export function hasUnsafeFilesystemId(value: string): boolean {
  const normalized = String(value || '')
  return normalized.includes('/') || normalized.includes('\\') || normalized.includes('..')
}

/**
 * 把任意输入压成适合文件名的片段，避免 `/` 把 preset_id 切成子目录。
 */
export function sanitizeFilesystemIdPart(value: string): string {
  return String(value || '')
    .trim()
    .replace(/[\\/]+/g, '-')
    .replace(/\.{2,}/g, '-')
    .replace(/\s+/g, '-')
    .replace(/[^a-zA-Z0-9._:-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
}

/**
 * 根据 provider id 和模型名生成更安全的默认 preset_id。
 */
export function derivePresetId(providerId: string, model: string): string {
  const providerPart = sanitizeFilesystemIdPart(providerId)
  const modelPart = sanitizeFilesystemIdPart(model)
  if (!providerPart || !modelPart) {
    return ''
  }
  return `${providerPart}--${modelPart}`
}

/**
 * 把 litellm 的能力信息映射成 UI 使用的 capability 列表。
 */
export function detectCapabilities(info: LitellmModelInfo | null | undefined): Capability[] {
  if (!info) {
    return []
  }
  const capabilities: Capability[] = []
  if (info.supports_function_calling) capabilities.push('tool_calling')
  if (info.supports_vision) capabilities.push('image_input')
  if (info.supports_reasoning) capabilities.push('reasoning')
  if (info.supports_response_schema) capabilities.push('structured_output')
  if (info.supports_audio_input) capabilities.push('audio_input')
  if (info.supports_audio_output) capabilities.push('audio_output')
  return capabilities
}

/**
 * 根据“字段是否已被用户修改”来决定是否应用 litellm 自动填充。
 */
export function applyLitellmAutofill(args: {
  draft: PresetAutofillDraft
  touched: PresetTouchedState
  modelInfo: LitellmModelInfo | null | undefined
}): PresetAutofillDraft {
  const { draft, touched, modelInfo } = args
  const next: PresetAutofillDraft = {
    context_window: draft.context_window,
    max_output_tokens: draft.max_output_tokens,
    capabilities: [...draft.capabilities],
  }
  if (!modelInfo) {
    return next
  }
  if (!touched.context_window && modelInfo.max_input_tokens) {
    next.context_window = String(modelInfo.max_input_tokens)
  }
  if (!touched.max_output_tokens && modelInfo.max_output_tokens) {
    next.max_output_tokens = String(modelInfo.max_output_tokens)
  }
  if (!touched.capabilities) {
    next.capabilities = detectCapabilities(modelInfo)
  }
  return next
}

/**
 * 生成 Provider 保存载荷，并保留界面未展开编辑的 query/body 配置。
 */
export function buildProviderSavePayload(draft: ProviderSaveDraft): ProviderSavePayload {
  return {
    name: draft.name.trim() || draft.provider_id.trim(),
    kind: draft.kind,
    base_url: draft.base_url,
    api_key_env: draft.api_key_env,
    api_key: draft.api_key,
    anthropic_version: draft.anthropic_version,
    api_version: draft.api_version,
    project_id: draft.project_id,
    location: draft.location,
    use_vertex_ai: draft.use_vertex_ai,
    default_headers: Object.fromEntries(
      draft.default_headers
        .filter((entry) => entry.key.trim())
        .map((entry) => [entry.key.trim(), entry.value]),
    ),
    default_query: { ...(draft.default_query || {}) },
    default_body: { ...(draft.default_body || {}) },
  }
}
