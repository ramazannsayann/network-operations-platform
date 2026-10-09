import { Stack, Text, ThemeIcon, Title } from '@mantine/core'
import type { Icon } from '@tabler/icons-react'
import type { ReactNode } from 'react'

export function EmptyState({
  icon: IconComponent,
  title,
  body,
  action,
}: {
  icon: Icon
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <Stack align="center" gap="xs" py="xl" ta="center">
      <ThemeIcon size={48} radius="xl" variant="light" color="gray" aria-hidden>
        <IconComponent size={28} />
      </ThemeIcon>
      <Title order={3}>{title}</Title>
      {body && (
        <Text c="dimmed" maw={460}>
          {body}
        </Text>
      )}
      {action}
    </Stack>
  )
}
