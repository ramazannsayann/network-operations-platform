/**
 * Status badges: every status has an icon and a text label as well as a colour, so colour
 * is never the only signal.
 */
import { Badge } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import type { Schemas } from '../api/client'
import {
  COLLECTION_STATUS,
  ITEM_STATUS,
  JOB_STATUS,
  type Look,
  MANAGEMENT_STATUS,
} from './statusLooks'

function StatusBadge({ look, label }: { look: Look; label: string }) {
  const IconComponent = look.icon
  return (
    <Badge color={look.color} variant="light" leftSection={<IconComponent size={12} aria-hidden />}>
      {label}
    </Badge>
  )
}

export function ManagementStatusBadge({ status }: { status: Schemas['ManagementStatus'] }) {
  const { t } = useTranslation()
  return (
    <StatusBadge look={MANAGEMENT_STATUS[status]} label={t(`enums.managementStatus.${status}`)} />
  )
}

export function JobStatusBadge({ status }: { status: Schemas['JobStatus'] }) {
  const { t } = useTranslation()
  return <StatusBadge look={JOB_STATUS[status]} label={t(`enums.jobStatus.${status}`)} />
}

export function ItemStatusBadge({ status }: { status: Schemas['DiscoveryItemStatus'] }) {
  const { t } = useTranslation()
  return <StatusBadge look={ITEM_STATUS[status]} label={t(`enums.itemStatus.${status}`)} />
}

export function CollectionStatusBadge({ status }: { status: Schemas['CollectionStatus'] }) {
  const { t } = useTranslation()
  return (
    <StatusBadge look={COLLECTION_STATUS[status]} label={t(`enums.collectionStatus.${status}`)} />
  )
}
