/** Colour and icon of every status; badges add the translated text. */
import type { MantineColor } from '@mantine/core'
import {
  IconAlertTriangle,
  IconBan,
  IconCheck,
  IconCircleCheck,
  IconClock,
  IconCopy,
  IconHandStop,
  IconLoader2,
  IconLock,
  IconPlugConnectedX,
  IconQuestionMark,
  IconWorldOff,
  IconX,
  type Icon,
} from '@tabler/icons-react'

import type { Schemas } from '../api/client'

export interface Look {
  color: MantineColor
  icon: Icon
}

export const MANAGEMENT_STATUS: Record<Schemas['ManagementStatus'], Look> = {
  managed: { color: 'teal', icon: IconCircleCheck },
  out_of_scope: { color: 'gray', icon: IconWorldOff },
  auth_failed: { color: 'red', icon: IconLock },
  unreachable: { color: 'orange', icon: IconPlugConnectedX },
  unsupported_platform: { color: 'grape', icon: IconBan },
  manual: { color: 'blue', icon: IconHandStop },
}

export const JOB_STATUS: Record<Schemas['JobStatus'], Look> = {
  queued: { color: 'gray', icon: IconClock },
  running: { color: 'blue', icon: IconLoader2 },
  succeeded: { color: 'teal', icon: IconCheck },
  failed: { color: 'red', icon: IconX },
}

export const ITEM_STATUS: Record<Schemas['DiscoveryItemStatus'], Look> = {
  discovered: { color: 'teal', icon: IconCircleCheck },
  duplicate: { color: 'cyan', icon: IconCopy },
  auth_failed: { color: 'red', icon: IconLock },
  unreachable: { color: 'orange', icon: IconPlugConnectedX },
  out_of_scope: { color: 'gray', icon: IconWorldOff },
  unsupported_platform: { color: 'grape', icon: IconBan },
  no_mgmt_ip: { color: 'yellow', icon: IconQuestionMark },
}

export const COLLECTION_STATUS: Record<Schemas['CollectionStatus'], Look> = {
  running: { color: 'blue', icon: IconLoader2 },
  success: { color: 'teal', icon: IconCheck },
  partial: { color: 'yellow', icon: IconAlertTriangle },
  failed: { color: 'red', icon: IconX },
}
