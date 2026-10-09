export type ComponentStatus = 'ok' | 'error'

/** Body of GET /api/health (see backend/src/netops/api/health.py). */
export interface Health {
  status: 'ok' | 'degraded'
  version: string
  db: ComponentStatus
  redis: ComponentStatus
}

function isComponentStatus(value: unknown): value is ComponentStatus {
  return value === 'ok' || value === 'error'
}

function isHealth(value: unknown): value is Health {
  if (typeof value !== 'object' || value === null) return false
  const body = value as Record<string, unknown>
  return (
    (body.status === 'ok' || body.status === 'degraded') &&
    typeof body.version === 'string' &&
    isComponentStatus(body.db) &&
    isComponentStatus(body.redis)
  )
}

/** Fetch backend health. The API answers 503, with the same body, when a dependency is down. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', { signal, headers: { Accept: 'application/json' } })
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected response from the API: HTTP ${response.status}`)
  }
  const body: unknown = await response.json()
  if (!isHealth(body)) {
    throw new Error('The API returned a malformed health response')
  }
  return body
}
