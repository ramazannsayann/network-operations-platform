import type { Schemas } from '../../api/client'

/** The device's Config tab showing the diff of a change, or null without both versions. */
export function diffLink(change: Schemas['ConfigChange']): string | null {
  if (!change.before_version_id || !change.after_version_id) return null
  const params = new URLSearchParams({
    tab: 'config',
    view: 'diff',
    from: change.before_version_id,
    to: change.after_version_id,
  })
  return `/devices/${change.device.id}?${params.toString()}`
}
