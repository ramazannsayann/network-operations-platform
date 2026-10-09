import { Group, Text, ThemeIcon } from '@mantine/core'
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconLoader2,
  IconPlugConnectedX,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'

import { useHealth } from '../api/queries'

/** API health in the header (polled every 15 s): icon, text and colour. */
export function HealthIndicator() {
  const { t } = useTranslation()
  const { data, isPending, isError } = useHealth()
  let look = { color: 'gray', icon: IconLoader2, label: t('header.health.checking') }
  if (!isPending) {
    if (isError || !data) {
      look = { color: 'red', icon: IconPlugConnectedX, label: t('header.health.down') }
    } else if (data.status === 'ok') {
      look = { color: 'teal', icon: IconCircleCheck, label: t('header.health.ok') }
    } else {
      look = { color: 'orange', icon: IconAlertTriangle, label: t('header.health.degraded') }
    }
  }
  const IconComponent = look.icon
  return (
    <Group gap={6} wrap="nowrap" role="status" aria-live="polite">
      <ThemeIcon color={look.color} variant="light" size="md" radius="xl" aria-hidden>
        <IconComponent size={16} />
      </ThemeIcon>
      <Text size="sm" c={look.color === 'teal' ? undefined : look.color} visibleFrom="xs">
        {look.label}
      </Text>
    </Group>
  )
}
