import { Alert, Button, Code, Group, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../api/errors'

/** An API error, with the problem+json detail when the API sent one. */
export function ProblemAlert({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const problem = error instanceof ApiError ? error.problem : null
  const status = error instanceof ApiError ? error.status : null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <Alert
      color="red"
      variant="light"
      icon={<IconAlertTriangle aria-hidden />}
      title={problem?.title ?? t('common.apiError')}
      role="alert"
    >
      <Text size="sm">{problem?.detail ?? message}</Text>
      <Group gap="xs" mt="xs">
        {status !== null && <Code>HTTP {status}</Code>}
        {problem?.type && problem.type !== 'about:blank' && <Code>{problem.type}</Code>}
        {onRetry && (
          <Button size="xs" variant="light" color="red" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        )}
      </Group>
    </Alert>
  )
}
