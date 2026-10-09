import type { Schemas } from '../../api/client'

type Item = Schemas['DiscoveryRunItem']
type ItemStatus = Schemas['DiscoveryItemStatus']

/** Display order of the result groups. */
export const STATUS_ORDER: ItemStatus[] = [
  'discovered',
  'duplicate',
  'auth_failed',
  'unreachable',
  'out_of_scope',
  'unsupported_platform',
  'no_mgmt_ip',
]

export function groupItems(items: Item[]): [ItemStatus, Item[]][] {
  return STATUS_ORDER.map((status): [ItemStatus, Item[]] => [
    status,
    items.filter((item) => item.status === status),
  ]).filter(([, group]) => group.length > 0)
}
