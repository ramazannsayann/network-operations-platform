/**
 * Server state through TanStack Query. Every hook calls the typed client; errors are
 * ApiError (problem+json). Long-running work is polled (WebSocket comes with alarms, M3).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Schemas } from './client'
import { unwrap } from './errors'
import type { paths } from './schema'

export type DeviceListQuery = NonNullable<paths['/api/v1/devices']['get']['parameters']['query']>
export type TopologyQuery = NonNullable<paths['/api/v1/topology']['get']['parameters']['query']>
export type Layer = Schemas['TopologyLayer']
export type JobStatus = Schemas['JobStatus']

const ACTIVE_JOB: JobStatus[] = ['queued', 'running']
export const POLL_MS = 2000

export const keys = {
  health: ['health'] as const,
  devices: (query: DeviceListQuery) => ['devices', query] as const,
  device: (id: string) => ['device', id] as const,
  interfaces: (id: string) => ['device', id, 'interfaces'] as const,
  job: (id: string) => ['job', id] as const,
  discoveryRuns: ['discovery-runs'] as const,
  discoveryRun: (id: string) => ['discovery-run', id] as const,
  credentialProfiles: ['credential-profiles'] as const,
  locations: ['locations'] as const,
  topology: (query: TopologyQuery) => ['topology', query] as const,
  topologyChanges: (since: string, until?: string) => ['topology-changes', since, until] as const,
  layout: (layer: Layer) => ['topology-layout', layer] as const,
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET('/api/health', { signal })
      // 503 carries the same body when a dependency is down.
      return data ?? (response.status === 503 ? (error ?? null) : null)
    },
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useDevices(query: DeviceListQuery) {
  return useQuery({
    queryKey: keys.devices(query),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/devices', { params: { query }, signal })),
    placeholderData: keepPreviousData,
  })
}

export function useDevice(id: string) {
  return useQuery({
    queryKey: keys.device(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/devices/{device_id}', { params: { path: { device_id: id } }, signal }),
      ),
  })
}

export function useInterfaces(id: string) {
  return useQuery({
    queryKey: keys.interfaces(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/devices/{device_id}/interfaces', {
          params: { path: { device_id: id }, query: { limit: 500 } },
          signal,
        }),
      ),
  })
}

export function useRefreshDevice(id: string) {
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/devices/{device_id}/refresh', {
          params: { path: { device_id: id } },
          body: {},
        }),
      ),
  })
}

/** A job, polled while it is queued or running. */
export function useJob(id: string | null) {
  return useQuery({
    queryKey: keys.job(id ?? ''),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id ?? '' } }, signal })),
    enabled: id !== null,
    refetchInterval: (query) =>
      query.state.data && !ACTIVE_JOB.includes(query.state.data.status) ? false : POLL_MS,
  })
}

export function useDiscoveryRuns() {
  return useQuery({
    queryKey: keys.discoveryRuns,
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/discovery/runs', { params: { query: { limit: 20 } }, signal })),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ACTIVE_JOB.includes(run.status)) ? POLL_MS : false,
  })
}

export function useDiscoveryRun(id: string) {
  return useQuery({
    queryKey: keys.discoveryRun(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/discovery/runs/{run_id}', { params: { path: { run_id: id } }, signal }),
      ),
    refetchInterval: (query) =>
      query.state.data && !ACTIVE_JOB.includes(query.state.data.status) ? false : POLL_MS,
  })
}

export function useStartDiscovery() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['DiscoveryRunCreate']) =>
      unwrap(api.POST('/api/v1/discovery/runs', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.discoveryRuns }),
  })
}

export function useCredentialProfiles() {
  return useQuery({
    queryKey: keys.credentialProfiles,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/credential-profiles', {
          params: { query: { kind: ['ssh'], limit: 500 } },
          signal,
        }),
      ),
  })
}

export function useLocations() {
  return useQuery({
    queryKey: keys.locations,
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/locations', { params: { query: { limit: 500 } }, signal })),
    staleTime: 60_000,
  })
}

export function useTopology(query: TopologyQuery) {
  return useQuery({
    queryKey: keys.topology(query),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/topology', { params: { query }, signal })),
    placeholderData: keepPreviousData,
  })
}

export function useTopologyChanges(since: string, until?: string) {
  return useQuery({
    queryKey: keys.topologyChanges(since, until),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/topology/changes', {
          params: { query: until ? { since, until } : { since } },
          signal,
        }),
      ),
  })
}

export function useLayout(layer: Layer) {
  return useQuery({
    queryKey: keys.layout(layer),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/topology/layout', { params: { query: { layer } }, signal })),
  })
}

export function useSaveLayout(layer: Layer) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (positions: Schemas['NodePosition'][]) =>
      unwrap(
        api.PUT('/api/v1/topology/layout', { params: { query: { layer } }, body: { positions } }),
      ),
    onSuccess: (layout) => client.setQueryData(keys.layout(layer), layout),
  })
}
