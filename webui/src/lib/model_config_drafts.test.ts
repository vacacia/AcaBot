import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyLitellmAutofill,
  buildProviderSavePayload,
  derivePresetId,
  hasUnsafeFilesystemId,
  sanitizeFilesystemIdPart,
  type PresetAutofillDraft,
  type ProviderSaveDraft,
} from './model_config_drafts.ts'

test('derivePresetId 会把模型名里的路径字符清洗成安全 ID', () => {
  assert.equal(
    derivePresetId('deepseek-main', 'deepseek/deepseek-chat'),
    'deepseek-main--deepseek-deepseek-chat',
  )
  assert.equal(derivePresetId('', ''), '')
  assert.equal(derivePresetId('provider', 'model'), 'provider--model')
  assert.equal(sanitizeFilesystemIdPart('../../../etc/passwd'), 'etc-passwd')
  assert.equal(hasUnsafeFilesystemId('deepseek/main'), true)
  assert.equal(hasUnsafeFilesystemId('deepseek-main--deepseek-deepseek-chat'), false)
})

test('applyLitellmAutofill 只更新未被用户手动修改的字段', () => {
  const draft: PresetAutofillDraft = {
    context_window: '65536',
    max_output_tokens: '4096',
    capabilities: ['tool_calling'],
  }
  const next = applyLitellmAutofill({
    draft,
    touched: {
      context_window: false,
      max_output_tokens: true,
      capabilities: true,
    },
    modelInfo: {
      max_input_tokens: 128000,
      max_output_tokens: 8192,
      supports_function_calling: true,
      supports_reasoning: true,
      supports_vision: true,
      supports_response_schema: false,
      supports_audio_input: false,
      supports_audio_output: false,
    },
  })

  assert.equal(next.context_window, '128000')
  assert.equal(next.max_output_tokens, '4096')
  assert.deepEqual(next.capabilities, ['tool_calling'])
})

test('applyLitellmAutofill 在能力未触碰时会同步 litellm 能力', () => {
  const next = applyLitellmAutofill({
    draft: {
      context_window: '',
      max_output_tokens: '',
      capabilities: [],
    },
    touched: {
      context_window: true,
      max_output_tokens: true,
      capabilities: false,
    },
    modelInfo: {
      supports_function_calling: true,
      supports_reasoning: true,
    },
  })

  assert.deepEqual(next.capabilities, ['tool_calling', 'reasoning'])
})

test('buildProviderSavePayload 会保留未暴露在表单里的 default_query 与 default_body', () => {
  const draft: ProviderSaveDraft = {
    provider_id: 'openai-main',
    name: 'OpenAI Main',
    kind: 'openai_compatible',
    base_url: 'https://llm.example.com/v1',
    api_key_env: 'OPENAI_API_KEY',
    api_key: '',
    anthropic_version: '',
    api_version: '',
    project_id: '',
    location: '',
    use_vertex_ai: false,
    default_headers: [
      { key: 'X-Trace', value: '1' },
      { key: '', value: 'ignored' },
    ],
    default_query: { api_version: '2024-01-01' },
    default_body: { metadata: { source: 'ui' } },
  }

  assert.deepEqual(buildProviderSavePayload(draft), {
    name: 'OpenAI Main',
    kind: 'openai_compatible',
    base_url: 'https://llm.example.com/v1',
    api_key_env: 'OPENAI_API_KEY',
    api_key: '',
    anthropic_version: '',
    api_version: '',
    project_id: '',
    location: '',
    use_vertex_ai: false,
    default_headers: { 'X-Trace': '1' },
    default_query: { api_version: '2024-01-01' },
    default_body: { metadata: { source: 'ui' } },
  })
})
