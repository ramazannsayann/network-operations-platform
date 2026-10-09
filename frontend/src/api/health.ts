import { api, type Schemas } from './client'

export type Health = Schemas['HealthResponse']
export type ComponentStatus = Schemas['ComponentStatus']

/** Fetch backend health. The API answers 503, with the same body, when a dependency is down. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const { data, error, response } = await api.GET('/api/health', { signal })
  if (data) return data
  if (response.status === 503 && error) return error
  throw new Error(`Unexpected response from the API: HTTP ${response.status}`)
}
