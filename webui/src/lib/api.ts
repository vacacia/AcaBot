export type ApiResponse<T> = {
  ok: boolean
  data: T
  error?: string
}

type CacheEntry = {
  expiresAt: number
  value: unknown
}

type CacheValidator<T> = (value: unknown) => value is T

const PERSISTENT_STORAGE_PREFIX = "acabot.api.cache:"
const getCache = new Map<string, CacheEntry>()
const inflightGetRequests = new Map<string, Promise<unknown>>()
const DEFAULT_GET_CACHE_TTL_MS = 15000

export async function apiGet<T>(path: string, validate?: CacheValidator<T>): Promise<T> {
  const now = Date.now()
  const cached = getValidatedCacheEntry(path, getCache.get(path), validate)
  if (cached && cached.expiresAt > now) {
    return cached.value as T
  }
  const persisted = getValidatedCacheEntry(path, getPersistedCache(path), validate)
  if (persisted && persisted.expiresAt > now) {
    getCache.set(path, persisted)
    return persisted.value as T
  }
  const inflight = inflightGetRequests.get(path)
  if (inflight) {
    return (await inflight) as T
  }
  const request = apiRequest<T>(path, { method: "GET" }).then((value) => {
    if (validate && !validate(value)) {
      dropCacheEntry(path)
      throw new Error(`Malformed API response for ${path}`)
    }
    if (!path.startsWith("/api/system/logs")) {
      const entry = {
        value,
        expiresAt: Date.now() + DEFAULT_GET_CACHE_TTL_MS,
      }
      getCache.set(path, entry)
      persistCache(path, entry)
    }
    return value
  }).finally(() => {
    inflightGetRequests.delete(path)
  })
  inflightGetRequests.set(path, request as Promise<unknown>)
  return await request
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  invalidateApiCache(path)
  return apiRequest<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  })
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  invalidateApiCache(path)
  return apiRequest<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function apiDelete<T>(path: string): Promise<T> {
  invalidateApiCache(path)
  return apiRequest<T>(path, { method: "DELETE" })
}

export function peekCachedGet<T>(path: string, validate?: CacheValidator<T>): T | null {
  const cached = getValidatedCacheEntry(path, getCache.get(path), validate)
  if (cached) {
    return cached.value as T
  }
  const persisted = getValidatedCacheEntry(path, getPersistedCache(path), validate)
  if (persisted) {
    getCache.set(path, persisted)
    return persisted.value as T
  }
  return null
}

function getValidatedCacheEntry<T>(
  path: string,
  entry: CacheEntry | null | undefined,
  validate?: CacheValidator<T>,
): CacheEntry | null {
  if (!entry) {
    return null
  }
  if (!validate || validate(entry.value)) {
    return entry
  }
  dropCacheEntry(path)
  return null
}

function invalidateApiCache(path: string): void {
  const prefixes = cachePrefixesForPath(path)
  const inflightKeys = Array.from(inflightGetRequests.keys())
  for (const key of inflightKeys) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      inflightGetRequests.delete(key)
    }
  }
  const cacheKeys = Array.from(getCache.keys())
  for (const key of cacheKeys) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      getCache.delete(key)
    }
  }
  if (typeof localStorage === "undefined") {
    return
  }
  const keysToDelete: string[] = []
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index)
    if (key?.startsWith(PERSISTENT_STORAGE_PREFIX) && prefixes.some((prefix) => key.includes(prefix))) {
      keysToDelete.push(key)
    }
  }
  for (const key of keysToDelete) {
    localStorage.removeItem(key)
  }
}

function cachePrefixesForPath(path: string): string[] {
  if (path.startsWith("/api/memory/long-term/config")) {
    return ["/api/memory/long-term/config"]
  }
  if (path.startsWith("/api/memory/sticky-notes")) {
    return ["/api/memory/sticky-notes"]
  }
  if (path.startsWith("/api/models/providers")) {
    return ["/api/models/providers", "/api/models/bindings", "/api/models/targets", "/api/ui/catalog"]
  }
  if (path.startsWith("/api/models/presets")) {
    return ["/api/models/presets", "/api/models/bindings", "/api/models/targets", "/api/ui/catalog"]
  }
  if (path.startsWith("/api/models/targets")) {
    return ["/api/models/targets"]
  }
  if (path.startsWith("/api/models/bindings")) {
    return ["/api/models/bindings", "/api/models/targets", "/api/ui/catalog"]
  }
  if (path.startsWith("/api/prompt") || path.startsWith("/api/prompts")) {
    return ["/api/prompt", "/api/prompts"]
  }
  if (path.startsWith("/api/admins")) {
    return ["/api/admins", "/api/system/configuration"]
  }
  if (path.startsWith("/api/gateway/config")) {
    return ["/api/gateway/config", "/api/system/configuration"]
  }
  if (path.startsWith("/api/render/config")) {
    return ["/api/render/config", "/api/system/configuration"]
  }
  if (path.startsWith("/api/filesystem/config")) {
    return ["/api/filesystem/config", "/api/system/configuration"]
  }
  if (path.startsWith("/api/runtime/reload-config")) {
    return ["/api/runtime/reload-config", "/api/system/configuration", "/api/admins"]
  }
  if (path.startsWith("/api/system/plugins")) {
    return ["/api/system/plugins", "/api/status"]
  }
  if (path.startsWith("/api/soul")) {
    return ["/api/soul"]
  }
  if (path.startsWith("/api/sessions")) {
    return ["/api/sessions", "/api/ui/catalog"]
  }
  return [path]
}

function dropCacheEntry(path: string): void {
  getCache.delete(path)
  if (typeof localStorage === "undefined") {
    return
  }
  localStorage.removeItem(`${PERSISTENT_STORAGE_PREFIX}${path}`)
}

function persistCache(path: string, entry: CacheEntry): void {
  if (typeof localStorage === "undefined") {
    return
  }
  localStorage.setItem(`${PERSISTENT_STORAGE_PREFIX}${path}`, JSON.stringify(entry))
}

function getPersistedCache(path: string): CacheEntry | null {
  if (typeof localStorage === "undefined") {
    return null
  }
  const raw = localStorage.getItem(`${PERSISTENT_STORAGE_PREFIX}${path}`)
  if (!raw) {
    return null
  }
  try {
    const parsed = JSON.parse(raw) as CacheEntry
    if (typeof parsed.expiresAt !== "number") {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

async function apiRequest<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  })
  const payload = (await response.json()) as ApiResponse<T>
  if (!response.ok || payload.ok !== true) {
    throw new Error(payload.error || `HTTP ${response.status}`)
  }
  return payload.data
}
