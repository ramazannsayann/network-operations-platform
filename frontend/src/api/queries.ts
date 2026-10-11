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
export type ConfigBackupsQuery = NonNullable<
  paths['/api/v1/config-backups']['get']['parameters']['query']
>
export type ConfigChangesQuery = NonNullable<
  paths['/api/v1/config-changes']['get']['parameters']['query']
>
export type EventsQuery = NonNullable<paths['/api/v1/events']['get']['parameters']['query']>
export type UsersQuery = NonNullable<paths['/api/v1/users']['get']['parameters']['query']>
export type AuditQuery = NonNullable<paths['/api/v1/audit']['get']['parameters']['query']>

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
  configBackups: (query: ConfigBackupsQuery) => ['config-backups', query] as const,
  deviceConfigs: (id: string) => ['device', id, 'configs'] as const,
  configVersion: (id: string) => ['config-version', id] as const,
  configDiff: (from: string, to: string, context: number) =>
    ['config-diff', from, to, context] as const,
  configChanges: (query: ConfigChangesQuery) => ['config-changes', query] as const,
  events: (query: EventsQuery) => ['events', query] as const,
  sessions: ['auth', 'sessions'] as const,
  users: (query: UsersQuery) => ['users', query] as const,
  credentialProfile: (id: string) => ['credential-profile', id] as const,
  audit: (query: AuditQuery) => ['audit', query] as const,
}

// Lists that change as devices are backed up or send syslog.
const LIVE_MS = 15_000

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

/** "Refresh now"; ``kinds`` narrows it (e.g. ``['config']`` for a configuration backup). */
export function useRefreshDevice(id: string) {
  return useMutation({
    mutationFn: (kinds?: Schemas['CollectionKind'][]) =>
      unwrap(
        api.POST('/api/v1/devices/{device_id}/refresh', {
          params: { path: { device_id: id } },
          body: kinds ? { kinds } : {},
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

/** Profiles by name; discovery offers only the SSH ones, the admin page lists all. */
export function useCredentialProfiles(kind?: Schemas['CredentialKind']) {
  return useQuery({
    queryKey: [...keys.credentialProfiles, kind ?? 'all'],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/credential-profiles', {
          params: { query: { kind: kind ? [kind] : undefined, limit: 500 } },
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

// --- Configuration management (M4) ---------------------------------------------------------

export function useConfigBackups(query: ConfigBackupsQuery) {
  return useQuery({
    queryKey: keys.configBackups(query),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/config-backups', { params: { query }, signal })),
    placeholderData: keepPreviousData,
    refetchInterval: LIVE_MS,
  })
}

/** Every version of a device, newest first. */
export function useDeviceConfigs(id: string) {
  return useQuery({
    queryKey: keys.deviceConfigs(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/devices/{device_id}/configs', {
          params: { path: { device_id: id }, query: { limit: 500 } },
          signal,
        }),
      ),
    refetchInterval: LIVE_MS,
  })
}

/** A version's redacted text; versions never change, so it is cached for good. */
export function useConfigVersion(id: string | null) {
  return useQuery({
    queryKey: keys.configVersion(id ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/configs/{version_id}', {
          params: { path: { version_id: id ?? '' } },
          signal,
        }),
      ),
    enabled: id !== null,
    staleTime: Infinity,
  })
}

export function useConfigDiff(from: string | null, to: string | null, context = 3) {
  return useQuery({
    queryKey: keys.configDiff(from ?? '', to ?? '', context),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/configs/diff', {
          params: { query: { from: from ?? '', to: to ?? '', context_lines: context } },
          signal,
        }),
      ),
    enabled: from !== null && to !== null,
    staleTime: Infinity,
  })
}

export function useConfigChanges(query: ConfigChangesQuery) {
  return useQuery({
    queryKey: keys.configChanges(query),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/config-changes', { params: { query }, signal })),
    placeholderData: keepPreviousData,
    refetchInterval: LIVE_MS,
  })
}

export function useEvents(query: EventsQuery, live = true) {
  return useQuery({
    queryKey: keys.events(query),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/events', { params: { query }, signal })),
    placeholderData: keepPreviousData,
    refetchInterval: live ? 10_000 : false,
  })
}

// --- The signed-in user's account (M7) -------------------------------------------------------

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: Schemas['PasswordChange']) =>
      unwrap(api.POST('/api/v1/auth/password', { body })),
  })
}

export function useBeginMfa() {
  return useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/auth/mfa/enroll')) })
}

export function useConfirmMfa() {
  return useMutation({
    mutationFn: (code: string) =>
      unwrap(api.POST('/api/v1/auth/mfa/enroll/confirm', { body: { code } })),
  })
}

export function useDisableMfa() {
  return useMutation({
    mutationFn: (body: Schemas['MfaDisable']) =>
      unwrap(api.POST('/api/v1/auth/mfa/disable', { body })),
  })
}

export function useSessions() {
  return useQuery({
    queryKey: keys.sessions,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/sessions', { signal })),
  })
}

export function useRevokeSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE('/api/v1/auth/sessions/{session_id}', { params: { path: { session_id: id } } }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.sessions }),
  })
}

// --- Administration (M7, admins) ----------------------------------------------------------

export function useUsers(query: UsersQuery) {
  return useQuery({
    queryKey: keys.users(query),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/users', { params: { query }, signal })),
    placeholderData: keepPreviousData,
  })
}

function useUserMutation<T>(call: (variables: T) => Promise<unknown>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: call,
    onSuccess: () => client.invalidateQueries({ queryKey: ['users'] }),
  })
}

export function useCreateUser() {
  return useUserMutation((body: Schemas['UserCreate']) =>
    unwrap(api.POST('/api/v1/users', { body })),
  )
}

export function useUpdateUser() {
  return useUserMutation(({ id, body }: { id: string; body: Schemas['UserUpdate'] }) =>
    unwrap(api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: id } }, body })),
  )
}

export function useUserAction() {
  return useUserMutation(
    ({ id, action }: { id: string; action: 'deactivate' | 'reset-mfa' | 'unlock' }) => {
      const params = { path: { user_id: id } }
      if (action === 'deactivate')
        return unwrap(api.POST('/api/v1/users/{user_id}/deactivate', { params }))
      if (action === 'reset-mfa')
        return unwrap(api.POST('/api/v1/users/{user_id}/reset-mfa', { params }))
      return unwrap(api.POST('/api/v1/users/{user_id}/unlock', { params }))
    },
  )
}

export function useResetPassword() {
  return useUserMutation(({ id, body }: { id: string; body: Schemas['PasswordReset'] }) =>
    unwrap(
      api.POST('/api/v1/users/{user_id}/reset-password', {
        params: { path: { user_id: id } },
        body,
      }),
    ),
  )
}

export function useCredentialProfile(id: string | null) {
  return useQuery({
    queryKey: keys.credentialProfile(id ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/credential-profiles/{profile_id}', {
          params: { path: { profile_id: id ?? '' } },
          signal,
        }),
      ),
    enabled: id !== null,
  })
}

function useProfileMutation<T>(call: (variables: T) => Promise<unknown>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: call,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: keys.credentialProfiles })
      await client.invalidateQueries({ queryKey: ['credential-profile'] })
    },
  })
}

export function useCreateCredentialProfile() {
  return useProfileMutation((body: Schemas['CredentialProfileCreate']) =>
    unwrap(api.POST('/api/v1/credential-profiles', { body })),
  )
}

export function useUpdateCredentialProfile() {
  return useProfileMutation(
    ({ id, body }: { id: string; body: Schemas['CredentialProfileUpdate'] }) =>
      unwrap(
        api.PATCH('/api/v1/credential-profiles/{profile_id}', {
          params: { path: { profile_id: id } },
          body,
        }),
      ),
  )
}

export function useDeleteCredentialProfile() {
  return useProfileMutation((id: string) =>
    unwrap(
      api.DELETE('/api/v1/credential-profiles/{profile_id}', {
        params: { path: { profile_id: id } },
      }),
    ),
  )
}

export function useAudit(query: AuditQuery) {
  return useQuery({
    queryKey: keys.audit(query),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/audit', { params: { query }, signal })),
    placeholderData: keepPreviousData,
  })
}
