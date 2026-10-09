import { Button } from '@mantine/core'
import { IconMapQuestion } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '../components/EmptyState'

export function NotFound() {
  const { t } = useTranslation()
  return (
    <EmptyState
      icon={IconMapQuestion}
      title={t('common.notFound')}
      action={
        <Button component={Link} to="/topology" variant="light">
          {t('common.backHome')}
        </Button>
      }
    />
  )
}
