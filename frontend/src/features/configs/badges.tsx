import { Badge } from '@mantine/core'
import {
  IconBolt,
  IconCalendarTime,
  IconHandClick,
  IconRobot,
  IconUserExclamation,
  type Icon,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'

import type { Schemas } from '../../api/client'

const TRIGGER_ICON: Record<Schemas['ConfigTrigger'], Icon> = {
  scheduled: IconCalendarTime,
  change_event: IconBolt,
  manual: IconHandClick,
  pre_change: IconRobot,
  post_change: IconRobot,
}

/** Why a backup ran: on schedule, after a change event (syslog), by hand, around an M5 change. */
export function TriggerBadge({ trigger }: { trigger: Schemas['ConfigTrigger'] }) {
  const { t } = useTranslation()
  const IconComponent = TRIGGER_ICON[trigger]
  return (
    <Badge variant="outline" color="gray" leftSection={<IconComponent size={12} aria-hidden />}>
      {t(`enums.configTrigger.${trigger}`)}
    </Badge>
  )
}

/**
 * Changes made outside the platform stand out (violet, with an icon and text), without the
 * warning colours, which stay reserved for real problems.
 */
export function OriginBadge({ origin }: { origin: Schemas['ChangeOrigin'] }) {
  const { t } = useTranslation()
  return origin === 'external' ? (
    <Badge
      color="violet"
      variant="light"
      leftSection={<IconUserExclamation size={12} aria-hidden />}
    >
      {t('configs.origin.external')}
    </Badge>
  ) : (
    <Badge color="indigo" variant="light" leftSection={<IconRobot size={12} aria-hidden />}>
      {t('configs.origin.platform')}
    </Badge>
  )
}
